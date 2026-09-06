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

import asyncio
import itertools
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Protocol

from agent_core.lifecycle import run_agent_span_exit_hooks
from agent_core.control import ExecutionControl, _current_control

if TYPE_CHECKING:  # Avoid runtime import cycles; only needed for typing
    from collections.abc import AsyncGenerator
    from agent_core.turn._models import ExecutionContext

from agent_core.agent_capabilities import AgentCapabilities, _active_agent_capabilities

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

    def subscribe(self, handler: Callable[[AgentEvent], object]) -> None: ...

    def unsubscribe(self, handler: Callable[[AgentEvent], object]) -> None: ...


# Event sink bound for the current coroutine context. Set by turn_scope.
# publish_event routes through the sink's add_event so the in-memory log is
# updated synchronously before observers fan out — no race.
_current_conversation: ContextVar[EventSink | None] = ContextVar("assistant_events_current_conversation", default=None)


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
    agent_capabilities: AgentCapabilities | None = None,
    profile_name: str | None = None,
    correlation_id: str | None = None,
    *,
    execution: ExecutionContext | None = None,
) -> AsyncGenerator[str, None]:
    """Bind attribution and emit lifecycle for a caller-owned execution.

    Standalone agent core callers can omit execution to create a local scope. Runtime
    callers supply identity, control, and sink explicitly; no run registry or
    process-global nudge queue is created here.
    """
    capabilities = agent_capabilities if agent_capabilities is not None else AgentCapabilities([])
    if execution is not None:
        with execution.bind(agent_name or "", capabilities):
            async with _agent_lifecycle(
                execution.execution_id, execution.parent_execution_id, agent_name,
                instruction, profile_name, correlation_id,
            ):
                yield execution.execution_id
        return

    stack = _context_stack.get()
    context_id = _make_child_context_id(agent_name)
    parent_id = stack[-1][0] if stack else None
    stack_token = _context_stack.set((*stack, (context_id, agent_name)))
    capabilities_token = _active_agent_capabilities.set(capabilities)
    parent_control = _current_control.get()
    control = ExecutionControl()
    if parent_control is not None:
        control.stop_event = parent_control.stop_event
    control_token = _current_control.set(control)
    try:
        async with _agent_lifecycle(context_id, parent_id, agent_name, instruction, profile_name, correlation_id):
            yield context_id
    finally:
        _current_control.reset(control_token)
        _active_agent_capabilities.reset(capabilities_token)
        _context_stack.reset(stack_token)


@asynccontextmanager
async def _agent_lifecycle(
    context_id: str,
    parent_id: str | None,
    agent_name: str | None,
    instruction: str | None,
    profile_name: str | None,
    correlation_id: str | None,
) -> AsyncGenerator[None, None]:
    from agent_core.control import StopRequestedError

    publish_event(AgentEvent(payload=AgentStartedPayload(
        type="agent_started", agent_id=context_id, agent_name=agent_name or "",
        parent_agent_id=parent_id, instruction=instruction, profile_name=profile_name,
        correlation_id=correlation_id,
    )))
    status = "success"
    try:
        yield
    except (StopRequestedError, asyncio.CancelledError):
        status = "stopped"
        raise
    except Exception:
        status = "error"
        raise
    finally:
        try:
            await run_agent_span_exit_hooks(context_id)
        finally:
            publish_event(AgentEvent(payload=AgentCompletedPayload(
                type="agent_completed", agent_id=context_id, agent_name=agent_name or "", status=status,
            )))


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
