"""Tests for Anthropic capability discovery and thinking request modes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent_core.providers._anthropic import AnthropicProvider, _supported_message_kwargs


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
    provider._model_cache = None
    provider._model_details = None

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
    provider._model_cache = None
    provider._model_details = None

    kwargs = provider._build_kwargs(
        "claude-opus-4-5",
        [{"role": "user", "content": "hello"}],
        None,
        {"thinking_budget": "extended", "num_predict": 512},
        True,
    )

    assert kwargs["max_tokens"] == 2048
    assert kwargs["thinking"] == {"type": "enabled", "budget_tokens": 2047}


def _kwargs(model: str, options: dict, think: bool) -> dict:
    provider = AnthropicProvider.__new__(AnthropicProvider)
    provider._model_cache = None
    provider._model_details = None
    return provider._build_kwargs(model, [{"role": "user", "content": "hello"}], None, options, think)


@pytest.mark.unit
def test_thinking_without_a_level_uses_adaptive_on_newer_claude_models() -> None:
    kwargs = _kwargs("claude-haiku-5-5", {"num_predict": 8192}, True)

    assert kwargs["thinking"] == {"type": "adaptive"}
    assert "output_config" not in kwargs
    assert kwargs["max_tokens"] == 8192


@pytest.mark.unit
def test_thinking_does_not_force_a_temperature() -> None:
    kwargs = _kwargs("claude-opus-5-5", {"reasoning_effort": "high"}, True)

    assert "temperature" not in kwargs


@pytest.mark.unit
@pytest.mark.parametrize(
    "model",
    ["claude-haiku-5-5", "claude-opus-5-5", "claude-sonnet-5", "claude-opus-4-8"],
)
def test_models_that_reject_sampling_never_receive_it(model: str) -> None:
    options = {"temperature": 0.3, "top_p": 0.9, "top_k": 20}

    for think in (False, True):
        kwargs = _kwargs(model, options, think)

        assert not {"temperature", "top_p", "top_k"} & kwargs.keys()


@pytest.mark.unit
def test_older_models_drop_temperature_and_top_k_while_thinking() -> None:
    options = {"temperature": 0.3, "top_p": 0.97, "top_k": 20}

    thinking = _kwargs("claude-opus-4-5", options, True)
    plain = _kwargs("claude-opus-4-5", options, False)

    assert "temperature" not in thinking
    assert "top_k" not in thinking
    assert thinking["top_p"] == 0.97
    assert plain["temperature"] == 0.3
    assert plain["top_k"] == 20
    assert plain["top_p"] == 0.97


@pytest.mark.unit
def test_thinking_off_is_sent_to_claude_models_that_think_by_default() -> None:
    kwargs = _kwargs("claude-haiku-5-5", {}, False)

    assert kwargs["thinking"] == {"type": "disabled"}
    assert "output_config" not in kwargs


@pytest.mark.unit
@pytest.mark.parametrize("model", ["claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-2"])
def test_thinking_off_is_not_sent_to_claude_models_that_always_think(model: str) -> None:
    kwargs = _kwargs(model, {}, False)

    assert "thinking" not in kwargs


@pytest.mark.unit
def test_thinking_off_is_not_sent_to_models_with_a_token_budget() -> None:
    kwargs = _kwargs("claude-sonnet-4-5", {}, False)

    assert "thinking" not in kwargs


async def _listed_model(raw: dict) -> object:
    model = SimpleNamespace(id=raw["id"], model_dump=lambda: raw)
    provider = AnthropicProvider.__new__(AnthropicProvider)
    provider._model_cache = None
    provider._model_details = None
    provider._client = AsyncMock()
    provider._client.models.list.return_value = SimpleNamespace(data=[model])
    provider._model_cache = None
    provider._model_details = None
    provider._model_cache_at = 0.0
    [result] = await provider.list_models()
    return result


def _adaptive_capabilities(*, disabled: bool) -> dict:
    return {
        "thinking": {
            "supported": True,
            "types": {"adaptive": {"supported": True}, "disabled": {"supported": disabled}},
        },
        "effort": {
            "supported": True,
            **{level: {"supported": True} for level in ("low", "medium", "high", "xhigh", "max")},
        },
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_model_list_marks_thinking_required_when_it_cannot_be_disabled() -> None:
    always = await _listed_model({
        "id": "claude-new-model",
        "capabilities": _adaptive_capabilities(disabled=False),
    })
    optional = await _listed_model({
        "id": "claude-other-model",
        "capabilities": _adaptive_capabilities(disabled=True),
    })

    assert always.thinking_required is True
    assert optional.thinking_required is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_model_list_uses_the_catalog_default_thinking_level() -> None:
    model = await _listed_model({
        "id": "claude-haiku-5-5",
        "capabilities": _adaptive_capabilities(disabled=True),
    })

    assert model.thinking_default == "medium"


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
    provider._model_cache = None
    provider._model_details = None
    provider._client = AsyncMock()
    provider._client.models.list.return_value = SimpleNamespace(data=[model])
    provider._model_cache = None
    provider._model_details = None
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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_requests_follow_the_provider_listing_for_models_missing_from_the_catalog() -> None:
    raw = {"id": "claude-new-model", "capabilities": _adaptive_capabilities(disabled=True)}
    provider = AnthropicProvider.__new__(AnthropicProvider)
    provider._client = AsyncMock()
    provider._client.models.list.return_value = SimpleNamespace(
        data=[SimpleNamespace(id=raw["id"], model_dump=lambda: raw)],
    )
    provider._model_cache = None
    provider._model_details = None
    provider._model_cache_at = 0.0
    await provider.list_models()
    messages = [{"role": "user", "content": "hello"}]

    thinking = provider._build_kwargs("claude-new-model", messages, None, {}, True)
    off = provider._build_kwargs("claude-new-model", messages, None, {}, False)

    assert thinking["thinking"] == {"type": "adaptive"}
    assert off["thinking"] == {"type": "disabled"}


@pytest.mark.unit
@pytest.mark.parametrize("model", ["claude-sonnet-4-5", "claude-haiku-4-5", "claude-opus-4-1"])
def test_models_that_refuse_temperature_with_top_p_get_only_one(model: str) -> None:
    kwargs = _kwargs(model, {"temperature": 0.3, "top_p": 0.9}, False)

    assert kwargs["temperature"] == 0.3
    assert "top_p" not in kwargs
