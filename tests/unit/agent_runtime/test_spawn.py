"""Tests for the application spawn tool.

Focused on input-validation paths that don't require a running LLM —
specifically the disabled-profile refusal.
"""

import pytest

from functools import partial
from agent_runtime import AgentRunner, AgentRunRequest, RunSession
from conversations import get_or_create_conversation
from agent_runtime._spawn import make_spawn_tool
from agent_core.agent_capabilities import AgentCapabilities
from agent_core.context import ConversationHistory
from agent_core.control import ExecutionControl
from agent_core.turn import ExecutionContext


@pytest.fixture
def spawn_agent():
    runner = AgentRunner()
    session = RunSession(AgentRunRequest(
        conversation_id="conversation", message="test", attachments=None, profile_id="parent",
    ), "run", get_or_create_conversation)
    context = session.root_context
    with context.bind("PARENT", AgentCapabilities([])):
        yield make_spawn_tool(partial(runner._invoke_child, session, context))


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
