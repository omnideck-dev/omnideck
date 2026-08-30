"""Execute one complete application-level agent run."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from agent_runtime._models import AgentRunRequest, EventSink, RunAttachment
from agents import AgentProfile, build_agent, get_agent_profile
from agents.types import Agent
from artifacts import ArtifactsIndexWriter
from browser_profiles._assignment import (
    browser_profile_assignment_scope,
    resolve_browser_profile_assignment,
)
from browser_profiles._conversation import prepare_conversation_browser
from conversations import (
    BrowserTabsWriter,
    EventsLogWriter,
    TerminalWriter,
    save_conversation_profile,
)
from sdk import default_hooks, run_turn
from sdk.context import ContextManager, ConversationHistory, LLMCompactionStrategy
from sdk.events import (
    AgentEvent,
    ErrorPayload,
    TurnEndPayload,
    UserAttachment,
    UserMessagePayload,
    agent_span,
    publish_event,
)
from sdk.skills import build_agent_state, persist_loaded_skills
from sdk.turn import ToolLoopError, check_stop, turn_scope
from sdk.turn._turn import StopRequestedError
from tools.memory import load_memory
from tools.virtual_computer.receive_file import receive_attachment

logger = logging.getLogger(__name__)
_console = Console(stderr=True)

ConversationLoader = Callable[
    [str],
    Awaitable[ConversationHistory],
]


class AgentRunner:
    """Translate an application-level agent run into SDK turn execution.

    This boundary owns the setup shared by every delivery channel. The current
    implementation maps one run to one root turn, but callers depend on run
    semantics rather than the lower-level turn lifecycle.
    """

    def __init__(self, conversation_loader: ConversationLoader) -> None:
        self._conversation_loader = conversation_loader

    async def run(
        self,
        request: AgentRunRequest,
        *,
        emit: EventSink,
        stop_event: asyncio.Event,
    ) -> None:
        """Run until domain completion, publishing every event through ``emit``."""
        try:
            if not request.conversation_id:
                msg = "conversation_id is required"
                raise ValueError(msg)
            history = await self._conversation_loader(request.conversation_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to prepare agent run")
            _emit_terminal_error(emit)
            return

        await self._run_with_history(
            request,
            history=history,
            emit=emit,
            stop_event=stop_event,
        )

    async def _run_with_history(
        self,
        request: AgentRunRequest,
        *,
        history: ConversationHistory,
        emit: EventSink,
        stop_event: asyncio.Event,
    ) -> None:
        conversation_id = request.conversation_id
        try:
            observers = [
                EventsLogWriter(conversation_id).handle_event,
                BrowserTabsWriter(conversation_id).handle_event,
                TerminalWriter(conversation_id).handle_event,
                ArtifactsIndexWriter(conversation_id).handle_event,
                emit,
            ]
        except Exception:
            logger.exception("Failed to prepare event observers for '%s'", conversation_id)
            _emit_terminal_error(emit)
            return
        for observer in observers:
            history.subscribe(observer)

        agent_state = None
        try:
            # The scope begins as soon as persistence and delivery observers
            # exist. Setup failures can therefore become ordinary run events,
            # and a stop recorded by ActiveRunManager before this task starts
            # is observed before expensive setup or a provider request.
            async with turn_scope(
                history,
                conversation_id=conversation_id,
                stop_event=stop_event,
            ):
                try:
                    check_stop()
                    profile = _resolve_profile(request.profile_id)
                    active_agent = _build_agent_from_profile(profile)
                    _log_turn_start(profile)

                    user_content = request.message
                    attachments: list[UserAttachment] = []
                    if request.attachments:
                        user_content, attachments = _augment_message_with_attachments(
                            request.message,
                            request.attachments,
                        )

                    save_conversation_profile(conversation_id, profile.id)

                    # Fresh AgentState each turn: the profile's skills, plus
                    # any loaded in earlier turns and restored from metadata.
                    agent_state = await build_agent_state(
                        profile,
                        conversation_id=conversation_id,
                    )
                    browser_assignment = await resolve_browser_profile_assignment(profile)
                    await prepare_conversation_browser(
                        conversation_id,
                        agent_profile_id=profile.id,
                        browser_access=profile.browser_access,
                        configured_profile_id=browser_assignment.source_profile_id,
                        source_profile_id=browser_assignment.source_profile_id,
                    )
                    ctx_manager = ContextManager(
                        history=history,
                        agent_state=agent_state,
                        context_limit=active_agent.context_window,
                        agent_name=active_agent.name,
                        compaction_threshold=active_agent.compaction_threshold,
                        strategies=[
                            LLMCompactionStrategy(
                                threshold=active_agent.compaction_threshold,
                            ),
                        ],
                    )

                    logger.info(
                        "Agent run started: conv=%s agent=%s message=%.80s",
                        conversation_id,
                        active_agent.name,
                        user_content,
                    )
                    with browser_profile_assignment_scope(browser_assignment):
                        async with agent_span(
                            active_agent.name,
                            instruction=user_content,
                            agent_state=agent_state,
                            profile_name=profile.name,
                        ):
                            try:
                                publish_event(
                                    AgentEvent(
                                        payload=UserMessagePayload(
                                            type="user_message",
                                            content=request.message,
                                            attachments=attachments,
                                        )
                                    )
                                )
                            except Exception:  # pragma: no cover - defensive
                                logger.exception("Failed to publish user_message event")

                            # LoadedSkillHook adds current skill prompts before
                            # each model call; the base system message stays fresh.
                            _refresh_system_message(history, active_agent.instruction)
                            hooks = default_hooks(
                                active_agent,
                                max_iterations=active_agent.max_iterations,
                                ctx_manager=ctx_manager,
                            )
                            await run_turn(
                                history=history,
                                agent=active_agent,
                                hooks=hooks,
                            )
                except StopRequestedError:
                    # Propagate through turn_scope so it emits turn_end, then
                    # swallow outside the scope as a normal stopped outcome.
                    raise
                except ToolLoopError:
                    # run_turn already published the specific error. Swallow
                    # only after agent_span recorded an error completion.
                    logger.debug("Agent run failed; error already published")
                except Exception:
                    # Setup and other unexpected failures become one persisted
                    # generic error; turn_scope owns the following turn_end.
                    logger.exception("Error running agent for '%s'", conversation_id)
                    publish_event(
                        AgentEvent(
                            payload=ErrorPayload(
                                type="error",
                                message="An error occurred while processing your message.",
                            )
                        )
                    )
        except StopRequestedError:
            logger.info("Agent run for conversation '%s' stopped by user", conversation_id)
        finally:
            # Unsubscribe synchronously before awaiting observer drainage. If
            # cancellation interrupts the await, the cached history still
            # cannot leak writers into the next run.
            for observer in observers:
                history.unsubscribe(observer)
            await history.drain_observers()

        if agent_state is not None and agent_state.loaded_skill_ids:
            try:
                persist_loaded_skills(agent_state, conversation_id)
            except Exception:
                logger.exception(
                    "Failed to save loaded skills for '%s'",
                    conversation_id,
                )


def _resolve_profile(profile_id: str | None) -> AgentProfile:
    if not profile_id:
        msg = "profile_id is required"
        raise RuntimeError(msg)
    profile = get_agent_profile(profile_id)
    if profile is None:
        msg = f"Agent profile '{profile_id}' not found"
        raise RuntimeError(msg)
    if not profile.model:
        msg = "No model configured. Select a model in the agent profile settings."
        raise ValueError(msg)
    return profile


def _build_agent_from_profile(profile: AgentProfile) -> Agent:
    """Construct an Agent; per-turn skill tools live in AgentState."""
    return build_agent(profile, tools=[])


def _augment_message_with_attachments(
    message: str,
    run_attachments: Sequence[RunAttachment],
) -> tuple[str, list[UserAttachment]]:
    """Write attachments and return model text plus structured event metadata."""
    file_lines = []
    attachments: list[UserAttachment] = []
    for item in run_attachments:
        container_path = receive_attachment(
            base64_encoded=item.base64_encoded,
            content_type=item.content_type,
            filename=item.filename,
        )
        name = item.filename or "unnamed"
        file_lines.append(f"  - {name} ({item.content_type}) -> {container_path}")
        attachments.append(
            UserAttachment(
                filename=name,
                content_type=item.content_type,
                path=container_path,
            )
        )

    files_block = "\n".join(file_lines)
    augmented = f"{message}\n\n[Attached files written to virtual computer]\n{files_block}"
    return augmented, attachments


def _refresh_system_message(history: ConversationHistory, system_prompt: str) -> None:
    """Refresh the system prompt with memories stored during earlier runs."""
    instruction = system_prompt
    memory = load_memory()
    if memory:
        lines = "\n".join(f"  {key}: {entry.value}" for key, entry in memory.items())
        sep = "─" * 64
        memory_block = f"\n── Memory (persisted across sessions) ──────────────────────────\n{lines}\n{sep}\n"
        instruction = memory_block + instruction
    history.set_system_message(instruction)


def _log_turn_start(profile: AgentProfile) -> None:
    """Print a Rich panel showing the active profile and its settings."""
    body = Text()
    body.append("profile: ", style="bold")
    body.append(profile.name, style="bright_magenta")
    body.append(f" ({profile.id})", style="dim")
    body.append("\nmodel:   ", style="bold")
    body.append(profile.model or "—", style="bright_yellow")
    if profile.skills:
        body.append("\nskills:  ", style="bold")
        body.append(", ".join(profile.skills), style="bright_cyan")
    params = []
    if profile.temperature is not None:
        params.append(f"temp={profile.temperature}")
    if profile.top_k is not None:
        params.append(f"top_k={profile.top_k}")
    if profile.top_p is not None:
        params.append(f"top_p={profile.top_p}")
    if profile.repeat_penalty is not None:
        params.append(f"repeat_penalty={profile.repeat_penalty}")
    if profile.num_predict is not None:
        params.append(f"num_predict={profile.num_predict}")
    if profile.context_window is not None:
        params.append(f"ctx={profile.context_window}")
    if profile.compaction_threshold is not None:
        params.append(f"compact@{int(profile.compaction_threshold * 100)}%")
    if profile.think:
        params.append("think")
    if profile.reasoning_effort is not None:
        params.append(f"reasoning_effort={profile.reasoning_effort}")
    if profile.reasoning_summary is not None:
        params.append(f"reasoning_summary={profile.reasoning_summary}")
    if profile.thinking_budget is not None:
        params.append(f"thinking_budget={profile.thinking_budget}")
    if profile.max_iterations is not None:
        params.append(f"max_iter={profile.max_iterations}")
    if params:
        body.append("\nparams:  ", style="bold")
        body.append(", ".join(params), style="dim")

    _console.print(
        Panel(
            body,
            title="[bold bright_magenta]🤖 Agent Turn[/bold bright_magenta]",
            border_style="bright_magenta",
            expand=False,
        )
    )


def _emit_terminal_error(emit: EventSink) -> None:
    """Deliver a terminal failure when no conversation scope could be opened."""
    emit(
        AgentEvent(
            payload=ErrorPayload(
                type="error",
                message="An error occurred while processing your message.",
            )
        )
    )
    emit(AgentEvent(payload=TurnEndPayload(type="turn_end")))


__all__ = ["AgentRunner", "ConversationLoader", "EventSink"]
