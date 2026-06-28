"""Message handler for user prompts."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable, Sequence
from contextlib import suppress

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from agents import (
    AgentProfile,
    build_agent,
    get_agent_profile,
)
from agents.types import Agent, Data
from artifacts import ArtifactsIndexWriter
from conversations import (
    BrowserTabsWriter,
    EventsLogWriter,
    TerminalWriter,
    save_conversation_profile,
)
from sdk import (
    default_hooks,
    run_turn,
)
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
from sdk.turn import ToolLoopError, turn_scope
from sdk.turn._turn import StopRequestedError
from server._conversation_cache import get_or_create_conversation
from tools.memory import load_memory
from tools.virtual_computer.receive_file import receive_attachment

logger = logging.getLogger(__name__)
_console = Console(stderr=True)


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


def _refresh_system_message(history: ConversationHistory, system_prompt: str) -> None:
    """Re-inserts the system message at the start of history with up-to-date memory.

    Called before each model invocation so any memories stored during the previous
    turn are visible immediately.
    """
    instruction = system_prompt
    memory = load_memory()
    if memory:
        lines = "\n".join(f"  {k}: {e.value}" for k, e in memory.items())
        sep = "─" * 64
        memory_block = f"\n── Memory (persisted across sessions) ──────────────────────────\n{lines}\n{sep}\n"
        instruction = memory_block + instruction

    history.set_system_message(instruction)


def _augment_message_with_attachments(
    message: str, data: Sequence[Data]
) -> tuple[str, list[UserAttachment]]:
    """Write attachments to the virtual computer.

    Returns the LLM-facing augmented message text and the structured
    attachment metadata for the user_message event.
    """
    file_lines = []
    attachments: list[UserAttachment] = []
    for d in data:
        container_path = receive_attachment(
            base64_encoded=d.base64_encoded,
            content_type=d.content_type,
            filename=d.filename,
        )
        name = d.filename or "unnamed"
        file_lines.append(f"  - {name} ({d.content_type}) -> {container_path}")
        attachments.append(UserAttachment(
            filename=name,
            content_type=d.content_type,
            path=container_path,
        ))

    files_block = "\n".join(file_lines)
    augmented = f"{message}\n\n[Attached files written to virtual computer]\n{files_block}"
    return augmented, attachments


def _build_agent_from_profile(profile: AgentProfile) -> Agent:
    """Construct an Agent from an AgentProfile.

    Tools are composed per turn from the profile's skills (build_agent_state);
    the Agent itself carries none.
    """
    return build_agent(profile, tools=[])


async def _run_turn(
    *,
    history: ConversationHistory,
    active_agent: Agent,
    profile: AgentProfile,
    user_content: str,
    user_message_text: str,
    user_attachments: list[UserAttachment],
    conversation_id: str,
    handler: Callable[[AgentEvent], object],
) -> None:
    """Execute a single conversation turn: model calls, tool execution, persistence."""
    logger.info(
        "Turn started: conv=%s agent=%s message=%.80s",
        conversation_id,
        active_agent.name,
        user_content,
    )
    _log_turn_start(profile)

    conv_id = conversation_id

    # Fresh AgentState each turn: the profile's skills, plus any loaded mid-
    # conversation in earlier turns (restored by id from conversation metadata).
    agent_state = await build_agent_state(profile, conversation_id=conv_id)

    ctx_manager = ContextManager(
        history=history,
        agent_state=agent_state,
        context_limit=active_agent.context_window,
        agent_name=active_agent.name,
        compaction_threshold=active_agent.compaction_threshold,
        strategies=[
            LLMCompactionStrategy(threshold=active_agent.compaction_threshold),
        ],
    )

    events_log = EventsLogWriter(conv_id)
    # Panel state is excluded from the event log; these keep the bounded
    # sidecars (latest browser snapshot per tab, last N terminal commands)
    # current instead.
    browser_tabs = BrowserTabsWriter(conv_id)
    terminal = TerminalWriter(conv_id)
    # Indexes file_output events into the global artifacts catalog.
    artifacts_index = ArtifactsIndexWriter(conv_id)
    # Conversation owns the canonical event log. Observers — the disk writer
    # and the SSE bridge that streams to the response — subscribe before the
    # scope and unsubscribe after, so the turn_scope-owned turn_end at the
    # end of the turn still reaches them. publish_event writes inline, so the
    # model never reads a stale view.
    history.subscribe(events_log.handle_event)
    history.subscribe(browser_tabs.handle_event)
    history.subscribe(terminal.handle_event)
    history.subscribe(artifacts_index.handle_event)
    history.subscribe(handler)
    try:
        async with turn_scope(history, conversation_id=conversation_id):
            async with agent_span(
                active_agent.name, instruction=user_content, agent_state=agent_state, profile_name=profile.name
            ):
                try:
                    publish_event(AgentEvent(payload=UserMessagePayload(
                        type="user_message",
                        content=user_message_text,
                        attachments=user_attachments,
                    )))
                except Exception:  # pragma: no cover - defensive
                    logger.exception("Failed to publish user_message event")
                # The LoadedSkillHook appends the loaded-skill section before
                # each model call, so the system message just carries the
                # profile prompt — skill prompts are not baked in here.
                _refresh_system_message(history, active_agent.instruction)

                hooks = default_hooks(
                    active_agent,
                    max_iterations=active_agent.max_iterations,
                    ctx_manager=ctx_manager,
                )

                # The stop is swallowed OUTSIDE turn_scope (below), not
                # here: it has to propagate through agent_span so the root
                # records agent_completed(status="stopped"), and through
                # turn_scope so turn_end still closes the turn.
                await run_turn(
                    history=history,
                    agent=active_agent,
                    hooks=hooks,
                )
    except StopRequestedError:
        logger.info("Turn for conversation '%s' stopped by user", conv_id)
    finally:
        # Unsubscribe synchronously BEFORE the await: if this cleanup is
        # cancelled mid-drain, an awaited-first order would skip the
        # unsubscribes and leak observers on the cached history — the next
        # turn would then double-subscribe a new writer and append every
        # event to events.jsonl twice. Drain still flushes the final
        # turn_end: it waits on already-created observer tasks regardless
        # of the subscription list.
        history.unsubscribe(events_log.handle_event)
        history.unsubscribe(browser_tabs.handle_event)
        history.unsubscribe(terminal.handle_event)
        history.unsubscribe(artifacts_index.handle_event)
        history.unsubscribe(handler)
        await history.drain_observers()

    # Persist loaded skills so they survive across turns and restarts
    if agent_state.loaded_skill_ids:
        try:
            persist_loaded_skills(agent_state, conv_id)
        except Exception:
            logger.exception("Failed to save loaded skills for '%s'", conv_id)


async def handle_user_message(
    message: str,
    data: Sequence[Data] | None = None,
    *,
    profile_id: str | None = None,
    conversation_id: str,
) -> AsyncGenerator[AgentEvent, None]:
    """Handles a user message by sending it to the LLM and yielding events.

    Args:
        message: The user's message.
        data: Optional sequence of file attachment data.
        profile_id: Agent profile to use. Required.
        conversation_id: Conversation identifier for isolation. Required.

    Yields:
        AgentEvent: Events from the LLM.
    """
    if not conversation_id:
        msg = "conversation_id is required"
        raise ValueError(msg)
    history, _is_new = await get_or_create_conversation(conversation_id)

    user_content = message
    user_attachments: list[UserAttachment] = []
    if data:
        user_content, user_attachments = _augment_message_with_attachments(message, data)

    if not profile_id:
        msg = "profile_id is required"
        raise RuntimeError(msg)
    profile = get_agent_profile(profile_id)
    if profile is None:
        msg = f"Agent profile '{profile_id}' not found"
        raise RuntimeError(msg)

    if not profile.model:
        msg = "No model configured. Complete the setup wizard to select a model."
        raise ValueError(msg)

    # Lock this profile to the conversation so resuming it later restores the
    # same agent. The latest selection wins if the user switches mid-thread.
    save_conversation_profile(conversation_id, profile_id)

    try:
        # Bridge published events via a queue so we can stream them to the caller.
        queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()

        async def _queue_handler(evt: AgentEvent) -> None:
            try:
                await queue.put(evt)
            except Exception:  # pragma: no cover - defensive logging
                logger.exception("Failed to enqueue AgentEvent in message handler")

        active_agent = _build_agent_from_profile(profile)

        async def _producer() -> None:
            try:
                await _run_turn(
                    history=history,
                    active_agent=active_agent,
                    profile=profile,
                    user_content=user_content,
                    user_message_text=message,
                    user_attachments=user_attachments,
                    conversation_id=conversation_id,
                    handler=_queue_handler,
                )
            finally:
                await queue.put(None)

        producer_task = asyncio.create_task(_producer())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
            # The None sentinel arrived (producer's finally ran), but the
            # producer may have died on the way — e.g. agent setup failed
            # before any event sink existed. Awaiting here re-raises that
            # failure into the catch below so it reaches the user instead
            # of being swallowed by the suppress in the cleanup path.
            await producer_task
        finally:
            if not producer_task.done():
                producer_task.cancel()
            with suppress(Exception):
                await producer_task

    except ToolLoopError:
        # The turn itself failed: run_turn already published the error
        # event and turn_scope closed the turn with turn_end — both
        # reached the stream. Yielding another error here would render
        # the failure twice.
        logger.debug("Turn failed; error already surfaced on the stream")
    except Exception:
        logger.exception("Error handling user message")
        yield AgentEvent(
            payload=ErrorPayload(
                type="error",
                message="An error occurred while processing your message.",
            )
        )
        yield AgentEvent(payload=TurnEndPayload(type="turn_end"))
