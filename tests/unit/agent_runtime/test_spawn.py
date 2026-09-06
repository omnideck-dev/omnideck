"""Tests for the application spawn tool.

Focused on input-validation paths that don't require a running LLM —
specifically the disabled-profile refusal.
"""

import pytest

from functools import partial
from agent_runtime._runner import AgentRunner, _Execution
from agent_runtime._spawn import make_spawn_tool
from sdk.agent_capabilities import AgentCapabilities
from sdk.context import ConversationHistory
from sdk.control import ExecutionControl
from sdk.turn import ExecutionContext


@pytest.fixture
def spawn_agent():
    runner = AgentRunner()
    runner._executions["parent"] = _Execution("run", "conversation", None)
    context = ExecutionContext(
        execution_id="parent",
        conversation_id="conversation",
        run_id="run",
        event_sink=ConversationHistory(conversation_id="conversation"),
        control=ExecutionControl(),
    )
    with context.bind("PARENT", AgentCapabilities([])):
        yield make_spawn_tool(partial(runner._invoke_child, "parent"))


@pytest.fixture(autouse=True)
def _isolate_profiles(tmp_path, monkeypatch):
    """Point profiles at a temp directory for each test."""
    monkeypatch.setattr(
        "agents._agent_profiles._profiles_dir",
        lambda: tmp_path / "agent_profiles",
    )


@pytest.mark.unit
class TestSpawnAgentDisabledProfile:
    """spawn_agent refuses disabled profiles before touching any LLM."""

    async def test_disabled_profile_returns_error_string(self, spawn_agent):
        """Disabled profile produces a clear error string, no LLM call."""
        from agents._agent_profiles import AgentProfile, save_agent_profile

        save_agent_profile(
            AgentProfile(
                id="off",
                name="Off",
                model="m",
                enabled=False,
            )
        )

        result = await spawn_agent(
            instructions="do something",
            agent_name="SUB",
            profile="off",
        )
        assert "disabled" in result
        assert "'off'" in result
        assert "list_agent_profiles" in result

    async def test_unknown_profile_returns_error_string(self, spawn_agent):
        """Unknown profile ID produces a clear error string, no LLM call."""
        result = await spawn_agent(
            instructions="do something",
            agent_name="SUB",
            profile="ghost",
        )
        assert "not found" in result
        assert "'ghost'" in result
        assert "list_agent_profiles" in result
