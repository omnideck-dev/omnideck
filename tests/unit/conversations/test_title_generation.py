from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from conversations._title_generation import generate_conversation_title
from sdk.providers._models import ChatMessage, ChatResponse, ModelInfo


@pytest.mark.unit
@pytest.mark.asyncio
async def test_title_generation_uses_native_sampling_with_small_output_cap():
    provider = MagicMock()
    provider.list_models = AsyncMock(return_value=[ModelInfo(
        name="openai.gpt-5.6-luna",
        max_output_tokens=128_000,
        inference_controls=["temperature", "top_p", "num_predict"],
    )])
    provider.chat = AsyncMock(return_value=ChatResponse(
        message=ChatMessage(content="Model Aware Defaults"),
    ))

    with patch("conversations._title_generation.load_settings", return_value={
        "title_provider": "aperture",
        "title_model": "openai.gpt-5.6-luna",
    }), patch("conversations._title_generation.get_provider", return_value=provider):
        title = await generate_conversation_title("Fix specialized model defaults")

    assert title == "Model Aware Defaults"
    options = provider.chat.await_args.kwargs["options"]
    assert options == {"num_predict": 50}
    assert "temperature" not in options
