from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm import ChatMessage, ChatResponse, ModelInfo
from conversations._title_generation import generate_conversation_title


@pytest.mark.unit
@pytest.mark.asyncio
async def test_title_generation_uses_native_sampling_with_small_output_cap():
    client = MagicMock()
    client.list_models = AsyncMock(return_value=[ModelInfo(
        name="openai.gpt-5.6-luna",
        max_output_tokens=128_000,
        inference_controls=["temperature", "top_p", "num_predict"],
    )])
    client.chat = AsyncMock(return_value=ChatResponse(
        message=ChatMessage(content="Model Aware Defaults"),
    ))

    with patch("utility_models._calls.load_settings", return_value={
        "title_provider": "aperture",
        "title_model": "openai.gpt-5.6-luna",
    }), patch("utility_models._calls.get_client", return_value=client):
        title = await generate_conversation_title("Fix specialized model defaults")

    assert title == "Model Aware Defaults"
    options = client.chat.await_args.kwargs["options"]
    assert options == {"num_predict": 50}
    assert "temperature" not in options
    assert client.chat.await_args.kwargs["model_info"].name == "openai.gpt-5.6-luna"
