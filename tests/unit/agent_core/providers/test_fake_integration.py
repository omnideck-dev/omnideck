"""Integration test: the real AgentExecutor.execute loop driven by the real FakeProvider.

Proves a directive prompt flows through the agent loop end-to-end — the fake
emits a tool call, the loop executes the (stub) tool, then the fake returns
the final reply — using the same code path the app uses.
"""

from unittest.mock import MagicMock, patch

import pytest
from tests.unit.agent_core._execution_inputs import execution_inputs

from agent_core.agent import Agent
from agent_core.context import ConversationHistory
from providers._fake import FakeProvider
from agent_core.agent_capabilities import AgentCapabilities, _active_agent_capabilities
from agent_core.turn import AgentExecutor
from tests.e2e._protocol import bash, say

_MOD = "agent_core.turn._execution"


def _agent() -> Agent:
    return Agent(
        name="fake-agent",
        description="test",
        instruction="You are a test agent.",
        provider="fake",
        model="fake-model",
        options={},

        think=False,
        max_iterations=0,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_directive_drives_tool_then_reply():
    calls: list[str] = []

    async def run_bash_cmd(cmd: str) -> str:
        """Stub bash tool that records the command."""
        calls.append(cmd)
        return f"RAN:{cmd}"

    history = ConversationHistory([
        {"role": "system", "content": "sys"},
        {"role": "user", "content": bash('echo "hi"') + say("finished")},
    ])

    cfg = MagicMock()
    cfg.enabled = False
    cfg.max_concurrent = 1

    token = _active_agent_capabilities.set(AgentCapabilities(base_tools=[run_bash_cmd]))
    try:
        # NOTE: do not patch ``publish_event`` here. The events-first
        # conftest bridge patches it with a forwarder that routes tool
        # results into history via handle_event — the only path by which
        # the loop's tool result reaches the history view. A no-op patch
        # overrides that forwarder, so the tool result never lands, the
        # fake planner re-emits the same BASH directive every iteration,
        # and the loop spins forever.
        provider = FakeProvider()
        execution = await AgentExecutor().execute(history=history, hooks=[], agent=_agent(), **execution_inputs(provider, 1))
        execution.raise_for_status()
        result = execution.output
    finally:
        _active_agent_capabilities.reset(token)

    # The fake emitted run_bash_cmd, the loop executed it, then the fake
    # returned the SAY reply.
    assert calls == ['echo "hi"']
    assert result == "finished"
    # History contains the tool result the loop recorded.
    assert any(m.get("role") == "tool" and m.get("tool_name") == "run_bash_cmd"
               for m in history.messages)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_plain_prompt_without_directives_echoes():
    history = ConversationHistory([
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello world"},
    ])

    token = _active_agent_capabilities.set(AgentCapabilities(base_tools=[]))
    try:
        provider = FakeProvider()
        execution = await AgentExecutor().execute(history=history, hooks=[], agent=_agent(), **execution_inputs(provider, 1))
        execution.raise_for_status()
        result = execution.output
    finally:
        _active_agent_capabilities.reset(token)

    assert result == "hello world"
