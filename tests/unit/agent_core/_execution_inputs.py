"""Explicit executor inputs for tests using the unit history fixture."""

from unittest.mock import MagicMock

from agent_core.agent_capabilities import AgentCapabilities, get_active_agent_capabilities
from agent_core.control import ExecutionControl, _current_control
from agent_core.events._context import _context_stack, get_current_conversation
from agent_core.turn import ExecutionContext


def execution_inputs(provider, max_parallel_tools=1):
    stack = _context_stack.get()
    return dict(
        provider=provider,
        capabilities=get_active_agent_capabilities() or AgentCapabilities([]),
        max_parallel_tools=max_parallel_tools,
        context=ExecutionContext(
            run_id="test", conversation_id="test",
            execution_id=stack[-1][0] if stack else "test-agent",
            ancestors=stack[:-1],
            event_sink=get_current_conversation() or MagicMock(),
            control=_current_control.get() or ExecutionControl(),
        ),
    )
