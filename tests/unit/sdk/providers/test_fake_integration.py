"""Integration test: the real run_turn loop driven by the real FakeProvider.

Proves a directive prompt flows through the agent loop end-to-end — the fake
emits a tool call, the loop executes the (stub) tool, then the fake returns
the final reply — using the same code path the app uses.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agents.types import Agent
from sdk.context import ConversationHistory
from sdk.providers._fake import FakeProvider
from sdk.skills.agent_state import AgentState, _active_agent_state
from tests.e2e._protocol import bash, say
from sdk.turn._execution import run_turn

_MOD = "sdk.turn._execution"


def _agent() -> Agent:
    return Agent(
        name="fake-agent",
        description="test",
        instruction="You are a test agent.",
        provider="fake",
        model="fake-model",
        options={},
        tools=[],
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

    token = _active_agent_state.set(AgentState(base_tools=[run_bash_cmd]))
    try:
        with (
            patch(f"{_MOD}.get_provider", return_value=FakeProvider()),
            patch(f"{_MOD}._get_parallel_config", return_value=cfg),
            patch(f"{_MOD}.publish_event"),
            patch(f"{_MOD}.get_current_agent_name", return_value="fake-agent"),
        ):
            result = await run_turn(history, _agent(), hooks=[])
    finally:
        _active_agent_state.reset(token)

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

    token = _active_agent_state.set(AgentState(base_tools=[]))
    try:
        with (
            patch(f"{_MOD}.get_provider", return_value=FakeProvider()),
            patch(f"{_MOD}._get_parallel_config", return_value=MagicMock(enabled=False, max_concurrent=1)),
            patch(f"{_MOD}.publish_event"),
            patch(f"{_MOD}.get_current_agent_name", return_value="fake-agent"),
        ):
            result = await run_turn(history, _agent(), hooks=[])
    finally:
        _active_agent_state.reset(token)

    assert result == "hello world"
