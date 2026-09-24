"""React loop: iterative LLM-call → tool-execution cycle and turn lifecycle.

This package provides:
- ``AgentExecutor``: Execution engine driving the chat/tool loop.
- ``turn_scope``: Async context manager for standalone execution bindings.
- Accessors for the supplied execution context and cooperative stop signal.
"""

from ._execution import AgentExecutor
from ._models import ExecutionContext, ExecutionResult, ToolLoopError, get_execution_context
from agent_core.control import StopRequestedError
from ._turn import (
    check_stop,
    get_conversation_id,
    turn_scope,
)

__all__ = [
    "StopRequestedError",
    "ToolLoopError",
    "check_stop",
    "get_conversation_id",
    "AgentExecutor",
    "ExecutionContext",
    "get_execution_context",
    "ExecutionResult",
    "turn_scope",
]
