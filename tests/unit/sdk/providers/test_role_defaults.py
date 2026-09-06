from unittest.mock import AsyncMock

import pytest

from sdk.providers._models import ModelInfo
from sdk.providers._role_defaults import resolve_role_options


@pytest.mark.unit
@pytest.mark.asyncio
async def test_vision_uses_native_sampling_and_model_bounded_role_cap():
    provider = AsyncMock()
    provider.list_models.return_value = [ModelInfo(
        name="openai.gpt-5.6-luna",
        max_output_tokens=128_000,
        inference_controls=["temperature", "top_p", "num_predict"],
    )]

    options, info = await resolve_role_options(
        provider,
        "openai.gpt-5.6-luna",
        "vision",
        {"top_k": 20, "num_ctx": 60_000},
    )

    assert info is not None
    assert options == {"num_predict": 512}
    assert "temperature" not in options


@pytest.mark.unit
@pytest.mark.asyncio
async def test_role_cap_never_exceeds_selected_model_output_limit():
    provider = AsyncMock()
    provider.list_models.return_value = [ModelInfo(
        name="tiny",
        max_output_tokens=32,
        inference_controls=["num_predict"],
    )]

    options, _ = await resolve_role_options(provider, "tiny", "title")

    assert options == {"num_predict": 32}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_explicit_compatible_override_is_preserved():
    provider = AsyncMock()
    provider.list_models.return_value = [ModelInfo(
        name="claude",
        max_output_tokens=16_384,
        inference_controls=["temperature", "top_k", "top_p", "num_predict"],
    )]

    options, _ = await resolve_role_options(
        provider,
        "claude",
        "compaction",
        {"temperature": 0.1, "top_k": 10, "num_predict": 2048},
    )

    assert options == {"temperature": 0.1, "top_k": 10, "num_predict": 2048}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_explicit_output_override_is_bounded_by_model_limit():
    provider = AsyncMock()
    provider.list_models.return_value = [ModelInfo(
        name="small-output-model",
        max_output_tokens=1024,
        inference_controls=["num_predict"],
    )]

    options, _ = await resolve_role_options(
        provider,
        "small-output-model",
        "compaction",
        {"num_predict": 4096},
    )

    assert options == {"num_predict": 1024}
