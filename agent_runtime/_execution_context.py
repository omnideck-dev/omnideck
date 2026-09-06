"""Compose SDK execution inputs from the application's current run scope."""

from config import load_config
from sdk.control import _current_control
from sdk.events._context import _context_stack, get_current_conversation
from sdk.turn import ExecutionContext, get_conversation_id
from sdk.turn._models import _current_execution


def execution_context(*, run_id: str | None = None) -> ExecutionContext:
    """Capture the identities and resources already owned by the caller's scope."""
    stack = _context_stack.get()
    sink = get_current_conversation()
    control = _current_control.get()
    conversation_id = get_conversation_id()
    if not stack or sink is None or control is None or conversation_id is None:
        raise RuntimeError("Execution requires an application turn and agent scope")
    execution_id = stack[-1][0]
    parent = _current_execution.get()
    if run_id is None:
        if parent is None:
            raise RuntimeError("Root execution requires its run identity")
        run_id = parent.run_id
    return ExecutionContext(
        execution_id=execution_id,
        conversation_id=conversation_id,
        run_id=run_id,
        parent_execution_id=stack[-2][0] if len(stack) > 1 else None,
        ancestors=stack[:-1],
        event_sink=sink,
        control=control,
    )


def parallel_tool_limit() -> int:
    """Translate application policy into the SDK's concurrency limit."""
    config = load_config().parallel
    return config.max_concurrent if config.enabled else 1
