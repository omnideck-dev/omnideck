"""Execute one complete application-level agent run."""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from functools import partial

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from agent_runtime._models import AgentRunRequest, EventSink, RunAttachment
from agents import AgentProfile, get_agent_profile
from agent_runtime._factory import AgentFactory, persist_loaded_skills
from agent_runtime._spawn import make_spawn_tool
from artifacts import ArtifactsIndexWriter
from browser.runtime import get_browser_runtime
from agent_runtime._execution_context import execution_context, parallel_tool_limit
from conversations import (
    get_or_create_conversation,
    BrowserTabsWriter,
    EventsLogWriter,
    TerminalWriter,
    save_conversation_profile,
)
from sdk import AgentExecutor, default_hooks
from sdk.context import ContextManager, ConversationHistory, LLMCompactionStrategy
from sdk.events import (
    AgentEvent,
    ErrorPayload,
    TurnEndPayload,
    SpawnRequestedPayload,
    get_current_conversation,
    UserAttachment,
    UserMessagePayload,
    agent_span,
    publish_event,
)
from sdk.events._context import _make_child_context_id
from sdk.turn._models import _current_execution
from sdk.turn import ExecutionResult, get_conversation_id
from sdk.turn import ToolLoopError, check_stop, turn_scope
from sdk.control import StopRequestedError
from tools.virtual_computer.receive_file import receive_attachment

logger = logging.getLogger(__name__)
_console = Console(stderr=True)

ConversationLoader = Callable[
    [str],
    Awaitable[ConversationHistory],
]


@dataclass(frozen=True)
class _Execution:
    """Live application ownership retained while an execution and its children run."""

    run_id: str
    conversation_id: str
    parent_execution_id: str | None


class AgentRunner:
    """Translate an application-level agent run into SDK turn execution.

    This boundary owns the setup shared by every delivery channel. The current
    implementation maps one run to one root turn, but callers depend on run
    semantics rather than the lower-level turn lifecycle.
    """

    def __init__(
        self,
        conversation_loader: ConversationLoader = get_or_create_conversation,
        *,
        factory: AgentFactory | None = None,
    ) -> None:
        self._conversation_loader = conversation_loader
        self._factory = factory if factory is not None else AgentFactory()
        self._executions: dict[str, _Execution] = {}

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
                    profile = self._factory.resolve_profile(request.profile_id)
                    _log_turn_start(profile)

                    user_content = request.message
                    attachments: list[UserAttachment] = []
                    if request.attachments:
                        user_content, attachments = _augment_message_with_attachments(
                            request.message,
                            request.attachments,
                        )

                    save_conversation_profile(conversation_id, profile.id)

                    await self.execute(
                        profile=profile,
                        history=history,
                        message=request.message,
                        instruction=user_content,
                        attachments=attachments,
                        run_id=request.run_id or f"run_{uuid4().hex}",
                        restore_skills=True,
                        persist_skills=True,
                        include_memory=True,
                    )
                except StopRequestedError:
                    # Propagate through turn_scope so it emits turn_end, then
                    # swallow outside the scope as a normal stopped outcome.
                    raise
                except ToolLoopError:
                    # AgentExecutor already published the specific error. Swallow
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

    async def execute(
        self,
        *,
        profile: AgentProfile,
        history: ConversationHistory | None = None,
        message: str,
        run_id: str,
        name: str | None = None,
        instruction: str | None = None,
        attachments: list[UserAttachment] | None = None,
        restore_skills: bool = False,
        persist_skills: bool = False,
        include_memory: bool = False,
        parent_execution_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ExecutionResult:
        """Prepare and execute an agent inside the caller's conversation scope.

        Interactive roots provide persisted history and opt into memory and skill
        restoration. Children receive a fresh history filtered to their identity.
        Routine tasks provide their own history and own conversation cleanup.
        """
        check_stop()
        # Conversation catalog readers still infer root depth from this shape.
        execution_id = _make_child_context_id(name or profile.name.upper())
        conversation_id = get_conversation_id()
        if not conversation_id:
            raise RuntimeError("AgentRunner.execute requires a conversation identity")
        sink = get_current_conversation()
        if sink is None:
            raise RuntimeError("AgentRunner.execute requires a conversation scope")
        if parent_execution_id is not None:
            parent = self._parent(parent_execution_id)
            if parent.run_id != run_id or parent.conversation_id != conversation_id:
                raise RuntimeError("Child execution must belong to its parent's run and conversation")
        elif _current_execution.get() is not None:
            raise RuntimeError("Nested execution requires an explicit parent")

        self._executions[execution_id] = _Execution(run_id, conversation_id, parent_execution_id)
        prepared = None
        child_history = None
        cancelled = False
        try:
            spawn_agent = make_spawn_tool(partial(self._invoke_child, execution_id))
            prepared = await self._factory.prepare(
                profile,
                spawn_agent=spawn_agent,
                name=name,
                restore_from_conversation=conversation_id if restore_skills else None,
                include_memory=include_memory,
            )
            agent = prepared.agent
            if parent_execution_id is not None:
                child_history = ConversationHistory(conversation_id=conversation_id, agent_id=execution_id)
                history = child_history
                sink.subscribe(history.handle_event)
            if history is None:
                raise RuntimeError("Root execution requires a history")
            history.set_system_message(prepared.system_prompt)
            ctx_manager = ContextManager(
                history=history,
                agent_capabilities=prepared.capabilities,
                context_limit=agent.context_window,
                agent_name=agent.name,
                compaction_threshold=agent.compaction_threshold,
                strategies=[LLMCompactionStrategy(threshold=agent.compaction_threshold)],
            )
            hooks = default_hooks(agent, max_iterations=agent.max_iterations, ctx_manager=ctx_manager)
            if correlation_id is not None:
                publish_event(
                    AgentEvent(
                        payload=SpawnRequestedPayload(
                            type="spawn_requested",
                            correlation_id=correlation_id,
                        )
                    )
                )
            async with agent_span(
                agent.name,
                instruction=instruction if instruction is not None else message,
                agent_capabilities=prepared.capabilities,
                profile_name=profile.name,
                correlation_id=correlation_id,
                execution_id=execution_id,
            ):
                await get_browser_runtime().prepare_current_agent_browser(
                    agent_profile_id=profile.id,
                    browser_profile_id=profile.browser_profile_id,
                )
                publish_event(
                    AgentEvent(
                        payload=UserMessagePayload(
                            type="user_message",
                            content=message,
                            attachments=attachments or [],
                        )
                    )
                )
                result = await AgentExecutor().execute(
                    history=history,
                    agent=agent,
                    capabilities=prepared.capabilities,
                    provider=prepared.provider,
                    context=execution_context(run_id=run_id),
                    max_parallel_tools=parallel_tool_limit(),
                    hooks=hooks,
                )
                result.raise_for_status()
                return result
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            self._executions.pop(execution_id)
            if child_history is not None:
                sink.unsubscribe(child_history.handle_event)
            if persist_skills and not cancelled and prepared is not None and prepared.capabilities.loaded_skill_ids:
                try:
                    persist_loaded_skills(prepared.capabilities, conversation_id)
                except Exception:
                    logger.exception("Failed to save loaded skills for '%s'", conversation_id)

    def _parent(self, execution_id: str) -> _Execution:
        parent = self._executions.get(execution_id)
        current = _current_execution.get()
        if parent is None or current is None or current.execution_id != execution_id:
            raise RuntimeError("Spawn tool is only valid inside its owning parent execution")
        return parent

    async def _invoke_child(self, parent_execution_id: str, instructions: str, profile: str, agent_name: str) -> str:
        parent = self._parent(parent_execution_id)
        check_stop()
        agent_profile = get_agent_profile(profile)
        if agent_profile is None:
            return f"Agent profile '{profile}' not found. Call list_agent_profiles() to see available profiles."
        if not agent_profile.enabled:
            return (
                f"Agent profile '{profile}' is disabled and cannot be used "
                "by spawn_agent. Call list_agent_profiles() to see available profiles."
            )
        correlation_id = uuid4().hex
        result = await self.execute(
            profile=agent_profile,
            message=instructions,
            run_id=parent.run_id,
            name=agent_name,
            parent_execution_id=parent_execution_id,
            correlation_id=correlation_id,
        )
        return (result.output or "").strip()


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
