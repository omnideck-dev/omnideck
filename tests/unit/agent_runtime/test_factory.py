"""Tests for agent_runtime._factory."""

import pytest

from agents import AgentProfile
from agent_runtime._factory import AgentFactory


def _make_profile(**overrides) -> AgentProfile:
    defaults = {
        "id": "test",
        "name": "Test",
        "provider": "ollama",
        "model": "test-model:7b",
        "system_prompt": "You are a test agent.",
    }
    defaults.update(overrides)
    return AgentProfile(**defaults)


@pytest.mark.unit
class TestBuildAgent:
    """Agent construction from profile."""

    def test_basic_conversion(self):
        """Profile fields flow through to the Agent."""
        p = _make_profile(temperature=0.5, top_k=40, think=True, context_window=16000)
        agent = AgentFactory.build_agent(p)
        assert agent.name == "TEST"
        assert agent.model == "test-model:7b"
        assert agent.think is True
        assert agent.instruction == "You are a test agent."
        assert agent.options == {"temperature": 0.5, "top_k": 40, "num_ctx": 16000}
        assert agent.context_window == 16000
        assert agent.compaction_threshold == 0.75

    def test_none_fields_omitted_from_options(self):
        """Unset profile fields don't appear in the options dict."""
        p = _make_profile()
        agent = AgentFactory.build_agent(p)
        assert agent.options == {}
        assert agent.max_iterations == 0
        assert agent.think is False

    def test_missing_model_raises(self):
        """Profile with no model raises RuntimeError."""
        p = _make_profile(id="child", model="")
        with pytest.raises(RuntimeError, match="not fully configured"):
            AgentFactory.build_agent(p)

    def test_missing_provider_raises(self):
        """Profile with no provider raises RuntimeError."""
        p = _make_profile(id="child", provider="")
        with pytest.raises(RuntimeError, match="not fully configured"):
            AgentFactory.build_agent(p)

    def test_name_override(self):
        """Explicit name takes precedence over profile name."""
        p = _make_profile()
        agent = AgentFactory.build_agent(p, name="CUSTOM")
        assert agent.name == "CUSTOM"
