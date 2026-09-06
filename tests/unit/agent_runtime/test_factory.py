"""Tests for agent_runtime._factory."""

import pytest

from agents import AgentProfile
from agent_core.providers import ModelInfo
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

    def test_cloud_context_is_not_sent_as_ollama_runtime_option(self):
        """Cloud context is local compaction metadata, not a provider option."""
        p = _make_profile(
            provider="aperture",
            model="openai/gpt-5.6-luna",
            context_window=1_050_000,
        )

        agent = AgentFactory.build_agent(p)

        assert "num_ctx" not in agent.options
        assert agent.context_window == 1_050_000

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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_runtime_metadata_drives_cloud_context_and_sanitizes_options():
    """Fixed cloud capacity and parameter support override stale profile data."""
    profile = _make_profile(
        provider="aperture",
        model="bedrock/openai.gpt-5.6-sol",
        context_window=32_000,
        temperature=0.7,
        top_p=0.9,
        reasoning_effort="high",
        think=True,
    )
    agent = AgentFactory.build_agent(profile)

    class _Provider:
        async def list_models(self):
            return [ModelInfo(
                name=profile.model,
                context_window=1_050_000,
                supports_thinking=True,
                inference_controls=[
                    "think", "reasoning_effort", "reasoning_summary",
                    "num_predict", "max_iterations", "compaction_threshold",
                ],
                thinking_levels=["none", "low", "medium", "high", "xhigh", "max"],
                is_cloud=True,
            )]

    resolved = await AgentFactory.resolve_runtime_metadata(agent, _Provider())

    assert resolved.context_window == 1_050_000
    assert resolved.options == {"reasoning_effort": "high"}
    assert resolved.think is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_runtime_metadata_keeps_configured_ollama_context():
    profile = _make_profile(context_window=16_000, temperature=0.7)
    agent = AgentFactory.build_agent(profile)

    class _Provider:
        async def list_models(self):
            return [ModelInfo(
                name=profile.model,
                context_window=128_000,
                inference_controls=["temperature", "context_window"],
            )]

    resolved = await AgentFactory.resolve_runtime_metadata(agent, _Provider())

    assert resolved.context_window == 16_000
    assert resolved.options == {"temperature": 0.7, "num_ctx": 16_000}
