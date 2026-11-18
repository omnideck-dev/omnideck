"""Tests for helper-role request options."""

from unittest.mock import AsyncMock

import pytest

from agent_core.providers import ModelInfo
from providers import resolve_role_options


def _provider(*models: ModelInfo) -> AsyncMock:
    provider = AsyncMock()
    provider.list_models.return_value = list(models)
    return provider


@pytest.mark.unit
async def test_vision_uses_native_sampling_and_model_bounded_role_cap():
    provider = _provider(ModelInfo(
        name="openai.gpt-5.6-luna",
        max_output_tokens=128_000,
        inference_controls=["temperature", "top_p", "num_predict"],
    ))

    request = await resolve_role_options(
        provider,
        "openai.gpt-5.6-luna",
        "vision",
        {"top_k": 20, "num_ctx": 60_000},
    )

    assert request.model is not None
    assert request.options == {"num_predict": 512}


@pytest.mark.unit
async def test_role_cap_never_exceeds_selected_model_output_limit():
    provider = _provider(ModelInfo(name="tiny", max_output_tokens=32, inference_controls=["num_predict"]))

    request = await resolve_role_options(provider, "tiny", "title")

    assert request.options == {"num_predict": 32}


@pytest.mark.unit
async def test_explicit_compatible_override_is_preserved():
    provider = _provider(ModelInfo(
        name="claude",
        max_output_tokens=16_384,
        inference_controls=["temperature", "top_k", "top_p", "num_predict"],
    ))

    request = await resolve_role_options(
        provider,
        "claude",
        "compaction",
        {"temperature": 0.1, "top_k": 10, "num_predict": 2048},
    )

    assert request.options == {"temperature": 0.1, "top_k": 10, "num_predict": 2048}


@pytest.mark.unit
async def test_explicit_output_override_is_bounded_by_model_limit():
    provider = _provider(ModelInfo(
        name="small-output-model",
        max_output_tokens=1024,
        inference_controls=["num_predict"],
    ))

    request = await resolve_role_options(provider, "small-output-model", "compaction", {"num_predict": 4096})

    assert request.options == {"num_predict": 1024}


@pytest.mark.unit
async def test_thinking_drops_values_the_model_refuses_while_thinking():
    provider = _provider(ModelInfo(
        name="claude-sonnet-4-5",
        supports_thinking=True,
        inference_controls=["temperature", "top_k", "top_p", "num_predict", "think"],
        thinking_excluded_controls=["temperature", "top_k"],
    ))

    request = await resolve_role_options(
        provider,
        "claude-sonnet-4-5",
        "vision",
        {"temperature": 0.3, "top_k": 20, "top_p": 0.9},
        think=True,
    )

    assert request.think is True
    assert request.options == {"top_p": 0.9, "num_predict": 512}


@pytest.mark.unit
async def test_thinking_follows_what_the_model_supports():
    provider = _provider(
        ModelInfo(name="no-thinking"),
        ModelInfo(name="always-thinks", supports_thinking=True, thinking_required=True),
    )

    assert (await resolve_role_options(provider, "no-thinking", "vision", think=True)).think is False
    assert (await resolve_role_options(provider, "always-thinks", "title")).think is True


@pytest.mark.unit
async def test_unknown_model_keeps_the_settings_and_the_role_cap():
    provider = _provider()

    request = await resolve_role_options(provider, "missing", "vision", {"temperature": 0.2}, think=True)

    assert request.model is None
    assert request.think is True
    assert request.options == {"temperature": 0.2, "num_predict": 512}
