"""React loop: iterative LLM-call → tool-execution cycle and turn lifecycle.

This package provides:
- ``AgentExecutor``: Execution engine driving the chat/tool loop.
- ``turn_scope``: Async context manager for conversation turn lifecycle.
- Stop/nudge signaling utilities for user-initiated control.
"""

from ._execution import AgentExecutor
from ._models import ExecutionContext, ExecutionResult, ToolLoopError
from ._nudge_queue import drain_nudges, queue_nudge, register_nudge_queue, unregister_nudge_queue
from sdk.control import StopRequestedError
from ._turn import (
    any_turn_active,
    check_stop,
    get_conversation_id,
    is_turn_active,
    request_stop,
    turn_scope,
)

__all__ = [
    "StopRequestedError",
    "ToolLoopError",
    "any_turn_active",
    "check_stop",
    "drain_nudges",
    "get_conversation_id",
    "is_turn_active",
    "queue_nudge",
    "register_nudge_queue",
    "request_stop",
    "AgentExecutor",
    "ExecutionContext",
    "ExecutionResult",
    "turn_scope",
    "unregister_nudge_queue",
]
