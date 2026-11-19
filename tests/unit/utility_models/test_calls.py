"""Tests for preparing utility-model calls."""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from llm import ModelInfo
from utility_models import configured_model, prepare_utility_call


def _client(*models: ModelInfo) -> AsyncMock:
    client = AsyncMock()
    client.list_models.return_value = list(models)
    return client


async def _prepare(utility: str, settings: dict[str, Any], client: AsyncMock, **kwargs: Any):
    with (
        patch("utility_models._calls.load_settings", return_value=settings),
        patch("utility_models._calls.get_client", return_value=client) as get_client,
    ):
        call = await prepare_utility_call(utility, **kwargs)  # type: ignore[arg-type]
    return call, get_client


@pytest.mark.unit
async def test_vision_uses_native_sampling_and_model_bounded_cap():
    client = _client(ModelInfo(
        name="openai.gpt-5.6-luna",
        max_output_tokens=128_000,
        inference_controls=["temperature", "top_p", "num_predict"],
    ))

    call, get_client = await _prepare("vision", {
        "vision_provider": "aperture",
        "vision_model": "openai.gpt-5.6-luna",
        "vision_options": {"top_k": 20, "num_ctx": 60_000},
    }, client)

    get_client.assert_called_once_with("aperture")
    assert call is not None
    assert call.client is client
    assert call.model_info is not None
    assert call.options == {"num_predict": 512}


@pytest.mark.unit
async def test_cap_never_exceeds_selected_model_output_limit():
    client = _client(ModelInfo(name="tiny", max_output_tokens=32, inference_controls=["num_predict"]))

    call, _ = await _prepare("title", {"title_provider": "ollama", "title_model": "tiny"}, client)

    assert call is not None
    assert call.options == {"num_predict": 32}


@pytest.mark.unit
async def test_explicit_compatible_override_is_preserved():
    client = _client(ModelInfo(
        name="claude",
        max_output_tokens=16_384,
        inference_controls=["temperature", "top_k", "top_p", "num_predict"],
    ))

    call, _ = await _prepare("compaction", {
        "compaction_provider": "anthropic",
        "compaction_model": "claude",
        "compaction_options": {"temperature": 0.1, "top_k": 10, "num_predict": 2048},
    }, client)

    assert call is not None
    assert call.options == {"temperature": 0.1, "top_k": 10, "num_predict": 2048}


@pytest.mark.unit
async def test_explicit_output_override_is_bounded_by_model_limit():
    client = _client(ModelInfo(name="small-output-model", max_output_tokens=1024, inference_controls=["num_predict"]))

    call, _ = await _prepare("compaction", {
        "compaction_provider": "ollama",
        "compaction_model": "small-output-model",
        "compaction_options": {"num_predict": 4096},
    }, client)

    assert call is not None
    assert call.options == {"num_predict": 1024}


@pytest.mark.unit
async def test_thinking_drops_values_the_model_refuses_while_thinking():
    client = _client(ModelInfo(
        name="claude-sonnet-4-5",
        supports_thinking=True,
        inference_controls=["temperature", "top_k", "top_p", "num_predict", "think"],
        thinking_excluded_controls=["temperature", "top_k"],
    ))

    call, _ = await _prepare("vision", {
        "vision_provider": "anthropic",
        "vision_model": "claude-sonnet-4-5",
        "vision_options": {"temperature": 0.3, "top_k": 20, "top_p": 0.9},
        "vision_think": True,
    }, client)

    assert call is not None
    assert call.think is True
    assert call.options == {"top_p": 0.9, "num_predict": 512}


@pytest.mark.unit
async def test_thinking_follows_what_the_model_supports():
    client = _client(
        ModelInfo(name="no-thinking"),
        ModelInfo(name="always-thinks", supports_thinking=True, thinking_required=True),
    )

    vision, _ = await _prepare("vision", {
        "vision_provider": "ollama", "vision_model": "no-thinking", "vision_think": True,
    }, client)
    title, _ = await _prepare("title", {"title_provider": "ollama", "title_model": "always-thinks"}, client)

    assert vision is not None and vision.think is False
    assert title is not None and title.think is True


@pytest.mark.unit
async def test_unknown_model_keeps_the_settings_and_the_cap():
    call, _ = await _prepare("vision", {
        "vision_provider": "ollama",
        "vision_model": "missing",
        "vision_options": {"temperature": 0.2},
        "vision_think": True,
    }, _client())

    assert call is not None
    assert call.model_info is None
    assert call.think is True
    assert call.options == {"temperature": 0.2, "num_predict": 512}


@pytest.mark.unit
async def test_titles_ignore_option_settings_they_do_not_have():
    client = _client(ModelInfo(name="m", inference_controls=["temperature", "num_predict"]))

    call, _ = await _prepare("title", {
        "title_provider": "ollama", "title_model": "m", "title_options": {"temperature": 1.5},
    }, client)

    assert call is not None
    assert call.options == {"num_predict": 50}


@pytest.mark.unit
async def test_a_model_override_replaces_the_configured_model():
    client = _client(ModelInfo(name="other", inference_controls=["num_predict"]))

    call, _ = await _prepare(
        "compaction", {"compaction_provider": "ollama", "compaction_model": "configured"}, client, model="other",
    )

    assert call is not None
    assert call.model == "other"


@pytest.mark.unit
@pytest.mark.parametrize("settings", [
    {"vision_provider": "", "vision_model": "m"},
    {"vision_provider": "ollama", "vision_model": ""},
])
async def test_unset_provider_or_model_means_no_call(settings):
    call, get_client = await _prepare("vision", settings, _client())

    assert call is None
    get_client.assert_not_called()
    with patch("utility_models._calls.load_settings", return_value=settings):
        assert configured_model("vision") is None
