"""Tests for agents._agent_builder."""

import pytest

from agents import AgentProfile, build_agent, resolve_agent_runtime_metadata
from sdk.providers import ModelInfo


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


def _noop() -> None:
    """Stub callable for tool lists."""


@pytest.mark.unit
class TestBuildAgent:
    """Agent construction from profile."""

    def test_basic_conversion(self):
        """Profile fields flow through to the Agent."""
        p = _make_profile(temperature=0.5, top_k=40, think=True, context_window=16000)
        agent = build_agent(p, tools=[_noop])
        assert agent.name == "TEST"
        assert agent.model == "test-model:7b"
        assert agent.think is True
        assert agent.instruction == "You are a test agent."
        assert agent.options == {"temperature": 0.5, "top_k": 40, "num_ctx": 16000}
        assert agent.context_window == 16000
        assert agent.compaction_threshold == 0.75
        assert agent.tools == [_noop]

    def test_none_fields_omitted_from_options(self):
        """Unset profile fields don't appear in the options dict."""
        p = _make_profile()
        agent = build_agent(p, tools=[])
        assert agent.options == {}
        assert agent.max_iterations == 0
        assert agent.think is False

    def test_cloud_context_is_local_compaction_metadata_not_provider_option(self):
        """Cloud APIs have fixed context capacities and must not receive num_ctx."""
        p = _make_profile(
            provider="aperture",
            model="openai.gpt-5.6-luna",
            context_window=1_050_000,
        )

        agent = build_agent(p, tools=[])

        assert "num_ctx" not in agent.options
        assert agent.context_window == 1_050_000

    def test_missing_model_raises(self):
        """Profile with no model raises RuntimeError."""
        p = _make_profile(id="child", model="")
        with pytest.raises(RuntimeError, match="not fully configured"):
            build_agent(p, tools=[])

    def test_missing_provider_raises(self):
        """Profile with no provider raises RuntimeError."""
        p = _make_profile(id="child", provider="")
        with pytest.raises(RuntimeError, match="not fully configured"):
            build_agent(p, tools=[])

    def test_name_override(self):
        """Explicit name takes precedence over profile name."""
        p = _make_profile()
        agent = build_agent(p, tools=[], name="CUSTOM")
        assert agent.name == "CUSTOM"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_runtime_metadata_drives_cloud_context_and_sanitizes_options(monkeypatch):
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
    agent = build_agent(profile, tools=[])

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

    monkeypatch.setattr("sdk.providers.get_provider", lambda _name: _Provider())

    resolved = await resolve_agent_runtime_metadata(agent)

    assert resolved.context_window == 1_050_000
    assert resolved.options == {"reasoning_effort": "high"}
    assert resolved.think is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_runtime_metadata_keeps_configured_ollama_context(monkeypatch):
    profile = _make_profile(context_window=16_000, temperature=0.7)
    agent = build_agent(profile, tools=[])

    class _Provider:
        async def list_models(self):
            return [ModelInfo(
                name=profile.model,
                context_window=128_000,
                inference_controls=["temperature", "context_window"],
            )]

    monkeypatch.setattr("sdk.providers.get_provider", lambda _name: _Provider())

    resolved = await resolve_agent_runtime_metadata(agent)

    assert resolved.context_window == 16_000
    assert resolved.options == {"temperature": 0.7, "num_ctx": 16_000}
