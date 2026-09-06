"""Tests for Anthropic capability discovery and thinking request modes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from sdk.providers._anthropic import AnthropicProvider, _supported_message_kwargs


@pytest.mark.unit
def test_request_kwargs_follow_installed_client_signature() -> None:
    """Bedrock SDK variants must not receive unsupported sampling fields."""
    def bedrock_stream(
        *,
        model: str,
        messages: list[dict],
        max_tokens: int,
        thinking: dict | None = None,
        output_config: dict | None = None,
    ) -> None:
        pass

    result = _supported_message_kwargs(bedrock_stream, {
        "model": "claude",
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 4096,
        "temperature": 1,
        "top_k": 20,
        "top_p": 0.9,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
        "cache_control": {"type": "ephemeral"},
    })

    assert result == {
        "model": "claude",
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 4096,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
    }


@pytest.mark.unit
def test_request_kwargs_leave_flexible_wrappers_untouched() -> None:
    def wrapped_stream(**kwargs: object) -> None:
        pass

    kwargs = {"model": "claude", "temperature": 0.5}

    assert _supported_message_kwargs(wrapped_stream, kwargs) is kwargs


@pytest.mark.unit
def test_adaptive_thinking_uses_output_effort() -> None:
    provider = AnthropicProvider.__new__(AnthropicProvider)

    kwargs = provider._build_kwargs(
        "claude-opus-5",
        [{"role": "user", "content": "hello"}],
        None,
        {"reasoning_effort": "xhigh", "num_predict": 8192},
        True,
    )

    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"] == {"effort": "xhigh"}
    assert "budget_tokens" not in kwargs["thinking"]


@pytest.mark.unit
def test_manual_thinking_budget_is_strictly_below_max_tokens() -> None:
    provider = AnthropicProvider.__new__(AnthropicProvider)

    kwargs = provider._build_kwargs(
        "claude-opus-4-5",
        [{"role": "user", "content": "hello"}],
        None,
        {"thinking_budget": "extended", "num_predict": 512},
        True,
    )

    assert kwargs["max_tokens"] == 2048
    assert kwargs["thinking"] == {"type": "enabled", "budget_tokens": 2047}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_model_list_uses_nested_anthropic_capabilities() -> None:
    raw = {
        "id": "claude-opus-5",
        "max_input_tokens": 1_000_000,
        "max_tokens": 128_000,
        "capabilities": {
            "image_input": {"supported": True},
            "thinking": {
                "supported": True,
                "types": {"adaptive": {"supported": True}},
            },
            "effort": {
                "supported": True,
                "low": {"supported": True},
                "medium": {"supported": True},
                "high": {"supported": True},
                "max": {"supported": True},
            },
        },
    }
    model = SimpleNamespace(id=raw["id"], model_dump=lambda: raw)
    provider = AnthropicProvider.__new__(AnthropicProvider)
    provider._client = AsyncMock()
    provider._client.models.list.return_value = SimpleNamespace(data=[model])
    provider._model_cache = None
    provider._model_cache_at = 0.0

    result = await provider.list_models()

    assert result[0].context_window == 1_000_000
    assert result[0].max_output_tokens == 128_000
    assert result[0].supports_images is True
    assert result[0].thinking_control == "reasoning_effort"
    assert result[0].thinking_levels == ["low", "medium", "high", "max"]
    assert result[0].thinking_default == "high"
    assert "reasoning_effort" in (result[0].inference_controls or [])
    assert "thinking_budget" not in (result[0].inference_controls or [])
