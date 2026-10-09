"""Explicit inputs and completion values for one agent core execution."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Literal

from agent_core.agent_capabilities import AgentCapabilities, _active_agent_capabilities
from agent_core.control import ExecutionControl, StopRequestedError, _current_control
from agent_core.events._context import EventSink, _context_stack, reset_current_conversation, set_current_conversation
from agent_core.providers import TokenUsage


_current_execution: ContextVar[ExecutionContext | None] = ContextVar("execution_context", default=None)


def get_execution_context() -> ExecutionContext | None:
    """Return the caller-supplied execution context bound to this coroutine."""
    return _current_execution.get()


class ToolLoopError(Exception):
    """An execution failed while processing a model or tool request."""


@dataclass(frozen=True)
class ExecutionContext:
    """Identity, event destination, and controls supplied by the execution owner.

    Binding does not emit lifecycle events or register a run. Those remain the
    caller's responsibility. Tools and hooks see these same explicit inputs
    through scoped convenience accessors.
    """

    execution_id: str
    conversation_id: str
    run_id: str
    event_sink: EventSink
    control: ExecutionControl
    parent_execution_id: str | None = None
    ancestors: tuple[tuple[str, str | None], ...] = ()

    @contextmanager
    def bind(self, name: str, capabilities: AgentCapabilities) -> Iterator[None]:
        from ._turn import _conversation_id

        conversation_token = _conversation_id.set(self.conversation_id)
        sink_token = set_current_conversation(self.event_sink)
        stack_token = _context_stack.set((*self.ancestors, (self.execution_id, name)))
        capabilities_token = _active_agent_capabilities.set(capabilities)
        control_token = _current_control.set(self.control)
        execution_token = _current_execution.set(self)
        try:
            yield
        finally:
            _current_execution.reset(execution_token)
            _current_control.reset(control_token)
            _active_agent_capabilities.reset(capabilities_token)
            _context_stack.reset(stack_token)
            reset_current_conversation(sink_token)
            _conversation_id.reset(conversation_token)


@dataclass(frozen=True)
class ExecutionResult:
    """Completion for this execution only; child usage is not counted here."""

    status: Literal["success", "stopped", "error"]
    output: str | None = None
    finish_reason: str | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    error: str | None = None
    retryable: bool = False

    def raise_for_status(self) -> None:
        """Propagate an unsuccessful outcome when the caller requires success."""
        if self.status == "stopped":
            raise StopRequestedError()
        if self.status == "error":
            raise ToolLoopError(self.error)
