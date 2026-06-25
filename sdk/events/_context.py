"""Context-bound event publishing for the events layer.

Exposes an asyncio-friendly API to publish AgentEvent events without threading
a sink handle through every call. A contextvars.ContextVar holds the event
sink bound for the current coroutine context (set by turn_scope for the
duration of a turn); publish_event writes each event into it.

Guidelines:
- The bound target is an EventSink — structurally, anything with add_event.
  It records the event synchronously and fans out to its own observers.
- Safe no-op when nothing is bound (tests, or code not running under a turn).
"""

from __future__ import annotations

import itertools
import logging
from contextlib import asynccontextmanager
from contextvars import ContextVar

from ._cleanup import run_agent_span_exit_hooks
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # Avoid runtime import cycles; only needed for typing
    from collections.abc import AsyncGenerator

from sdk.skills.agent_state import AgentState, _active_agent_state

from ._models import AgentCompletedPayload, AgentEvent, AgentStartedPayload

logger = logging.getLogger(__name__)


class EventSink(Protocol):
    """The write side of a conversation's event log.

    publish_event needs exactly one capability from whatever it is bound to:
    append an event, which the implementor records and fans out to its own
    observers. Declaring the dependency structurally lets the events layer stay
    unaware of the concrete conversation type, which avoids an import cycle.
    """

    def add_event(self, event: AgentEvent) -> None: ...


# Event sink bound for the current coroutine context. Set by turn_scope.
# publish_event routes through the sink's add_event so the in-memory log is
# updated synchronously before observers fan out — no race.
_current_conversation: ContextVar[EventSink | None] = ContextVar(
    "assistant_events_current_conversation", default=None
)


def get_current_conversation() -> EventSink | None:
    """Return the event sink bound for this context, or None."""
    return _current_conversation.get()


def set_current_conversation(conv: EventSink | None) -> object:
    """Bind an event sink as the active write target. Returns the reset token."""
    return _current_conversation.set(conv)


def reset_current_conversation(token: object) -> None:
    """Restore the previous binding."""
    _current_conversation.reset(token)  # type: ignore[arg-type]


# Stack of (context_id, agent_name) frames for nested agent/tool executions.
_context_stack: ContextVar[tuple[tuple[str, str | None], ...]] = ContextVar(
    "assistant_events_context_stack", default=()
)

_subcontext_counter = itertools.count(1)
_ROOT_CONTEXT_ID = "root"


def _make_child_context_id(label: str | None = None) -> str:
    """Create a child context id derived from the current stack top."""
    stack = _context_stack.get()
    parent_id = stack[-1][0] if stack else _ROOT_CONTEXT_ID
    raw = (label or "child").lower()
    safe = "".join(c if c.isalnum() else "_" for c in raw).strip("_") or "child"
    return f"{parent_id}.{safe}.{next(_subcontext_counter)}"


def get_current_agent_name() -> str | None:
    """Return the agent name from the top of the context stack, or None."""
    stack = _context_stack.get()
    return stack[-1][1] if stack else None


def get_current_agent_id() -> str | None:
    """Return the context id from the top of the context stack, or None."""
    stack = _context_stack.get()
    return stack[-1][0] if stack else None




def get_current_depth() -> int:
    """Return the current nesting depth (0 = root, 1+ = sub-agents)."""
    stack = _context_stack.get()
    return max(0, len(stack) - 1) if stack else 0


@asynccontextmanager
async def agent_span(
    agent_name: str | None = None,
    instruction: str | None = None,
    agent_state: AgentState | None = None,
    profile_name: str | None = None,
    correlation_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """Push an attribution frame for the duration of the block.

    Events published inside will be tagged with the given agent name and an
    incremented depth. Emits agent lifecycle events on entry and exit.

    When an AgentState is passed, the span borrows it (useful for multi-turn
    agents whose skills should survive across turns). Otherwise a fresh
    empty AgentState is created.

    On exit, releases any ephemeral browser context created by this agent
    (sub-agents only, depth > 0).

    Args:
        agent_name: Human-readable agent name for event attribution.
        instruction: The instruction or user message this agent was given.
        agent_state: AgentState to use for this span. A fresh empty one is
            created when None.
        profile_name: Name of the agent profile, shown in the UI.
        correlation_id: Id shared with a preceding SpawnRequestedPayload
            so the UI can attach this agent to the spawn that produced it.
            None for root agents.

    Yields:
        str: The context id pushed onto the stack.

    Example:
        async with agent_span("Browser Agent", instruction="Browse example.com"):
            publish_event(AgentEvent(payload=ContentPayload(type="content", thinking="Navigating...")))
    """
    stack = _context_stack.get()
    parent_id = stack[-1][0] if stack else None
    context_id = _make_child_context_id(agent_name)
    depth = len(stack)
    token = _context_stack.set((*stack, (context_id, agent_name)))
    # Borrow an existing AgentState (multi-turn agents) or create a fresh
    # one (sub-agents). Skills loaded mid-span persist for the span's
    # lifetime; a borrowed instance also preserves skills across spans.
    ls_token = _active_agent_state.set(agent_state if agent_state is not None else AgentState([]))

    # Lazy import: sdk.turn._nudge_queue is a leaf module with no internal
    # deps, but importing it at module level triggers sdk.turn.__init__ which
    # pulls in _execution.py → sdk.events (circular).
    from sdk.turn._nudge_queue import register_nudge_queue, unregister_nudge_queue

    register_nudge_queue(context_id)

    logger.info(
        "Agent started: %s (id=%s, parent=%s, depth=%d)",
        agent_name, context_id, parent_id, depth,
    )

    publish_event(AgentEvent(payload=AgentStartedPayload(
        type="agent_started",
        agent_id=context_id,
        agent_name=agent_name or "",
        parent_agent_id=parent_id,
        instruction=instruction,
        profile_name=profile_name,
        correlation_id=correlation_id,
    )))

    status = "success"
    try:
        yield context_id
    except Exception as exc:
        # Import here to avoid circular dependency with sdk.turn
        from sdk.turn._turn import StopRequestedError
        status = "stopped" if isinstance(exc, StopRequestedError) else "error"
        raise
    finally:
        await run_agent_span_exit_hooks(context_id)

        logger.info(
            "Agent completed: %s (id=%s, status=%s, depth=%d)",
            agent_name, context_id, status, depth,
        )
        publish_event(AgentEvent(payload=AgentCompletedPayload(
            type="agent_completed",
            agent_id=context_id,
            agent_name=agent_name or "",
            status=status,
        )))
        unregister_nudge_queue(context_id)
        _active_agent_state.reset(ls_token)
        _context_stack.reset(token)


def publish_event(event: AgentEvent) -> None:
    """Publish an AgentEvent to the active conversation.

    Enriches the event with the current agent name / depth / agent id
    from the context stack, then writes it to the conversation. The
    conversation appends synchronously and fans out to its observers
    (disk writer, SSE stream, etc.). No-op when no conversation is bound.

    Args:
        event: The AgentEvent instance to publish.
    """
    conv = _current_conversation.get()
    if conv is None:
        logger.debug("No active conversation; dropping event.")
        return

    stack = _context_stack.get()
    enriched = event.model_copy(
        update={
            "agent_name": stack[-1][1] if stack else None,
            "depth": len(stack) - 1 if stack else 0,
            "agent_id": stack[-1][0] if stack else None,
        }
    )
    try:
        conv.add_event(enriched)
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to add event to conversation")
