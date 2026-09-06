"""Tests for Tailscale Aperture discovery and protocol routing."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from sdk.providers._aperture import (
    ApertureProvider,
    _ApertureBedrockProvider,
    _enabled_models,
    _filter_catalog,
    _provider_list,
    _routes_from_catalog,
)
from sdk.providers._models import ChatDelta, ChatMessage, ChatResponse, ProviderError


def _catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": "openai",
            "name": "OpenAI",
            "models": ["gpt-5.4"],
            "compatibility": {"openai_chat": True, "openai_responses": True},
        },
        {
            "id": "anthropic",
            "name": "Anthropic",
            "models": ["claude-sonnet-4-6"],
            "compatibility": {"anthropic_messages": True},
        },
        {
            "id": "bedrock",
            "name": "Amazon Bedrock",
            "models": [
                "us.anthropic.claude-sonnet-4-6",
                "amazon.nova-pro-v1:0",
            ],
            "compatibility": {
                "bedrock_model_invoke": True,
                "bedrock_converse": True,
            },
        },
        {
            "id": "compatible",
            "name": "Internal models",
            "models": ["company-model"],
            "compatibility": {},
        },
        {
            "id": "gemini",
            "name": "Gemini",
            "models": ["gemini-3"],
            "compatibility": {"gemini_generate_content": True},
        },
    ]


class _FakeAdapter:
    def __init__(self) -> None:
        self.chat_calls: list[dict[str, Any]] = []
        self.invalidated = False

    async def chat(self, **kwargs: Any) -> ChatResponse:
        self.chat_calls.append(kwargs)
        return ChatResponse(message=ChatMessage(content="ok"), done_reason="stop")

    async def chat_stream(self, **kwargs: Any) -> AsyncGenerator[ChatDelta | ChatResponse, None]:
        self.chat_calls.append(kwargs)
        yield ChatDelta(content="o")
        yield ChatResponse(message=ChatMessage(content="ok"), done_reason="stop")

    async def list_models(self) -> list[Any]:
        return []

    def invalidate_model_cache(self) -> None:
        self.invalidated = True


@pytest.mark.unit
def test_routes_use_discovered_formats_and_hide_unsupported_bedrock_models() -> None:
    models, routes = _routes_from_catalog(_catalog())

    assert [model.name for model in models] == [
        "openai/gpt-5.4",
        "anthropic/claude-sonnet-4-6",
        "bedrock/us.anthropic.claude-sonnet-4-6",
        "compatible/company-model",
    ]
    assert routes["openai/gpt-5.4"].wire_api == "openai_responses"
    assert routes["anthropic/claude-sonnet-4-6"].wire_api == "anthropic_messages"
    assert routes["bedrock/us.anthropic.claude-sonnet-4-6"].wire_api == "bedrock_model_invoke"
    assert routes["bedrock/us.anthropic.claude-sonnet-4-6"].request_model == "us.anthropic.claude-sonnet-4-6"
    assert routes["compatible/company-model"].wire_api == "openai_chat"
    assert "bedrock/amazon.nova-pro-v1:0" not in routes
    assert "gemini/gemini-3" not in routes

    bedrock = next(model for model in models if model.name.startswith("bedrock/"))
    assert bedrock.display_name == "us.anthropic.claude-sonnet-4-6"
    assert bedrock.upstream_provider == "Amazon Bedrock"
    assert bedrock.wire_api == "Amazon Bedrock"
    assert bedrock.inference_api == "bedrock_model_invoke"
    assert bedrock.inference_controls is not None
    assert "reasoning_effort" in bedrock.inference_controls
    assert "thinking_budget" not in bedrock.inference_controls
    assert "temperature" not in bedrock.inference_controls
    assert "top_k" not in bedrock.inference_controls
    assert "top_p" not in bedrock.inference_controls
    assert bedrock.thinking_levels == ["low", "medium", "high", "max"]
    assert bedrock.thinking_default == "high"
    assert bedrock.supports_images is True
    assert bedrock.supports_thinking is True


@pytest.mark.unit
def test_provider_qualified_gpt_56_gets_responses_controls_and_limits() -> None:
    catalog = [{
        "id": "bedrock",
        "name": "Amazon Bedrock",
        "models": ["openai.gpt-5.6-luna"],
        "compatibility": {"openai_responses": True},
    }]

    models, _ = _routes_from_catalog(catalog)

    assert len(models) == 1
    model = models[0]
    assert model.name == "bedrock/openai.gpt-5.6-luna"
    assert model.inference_api == "openai_responses"
    assert model.context_window == 1_050_000
    assert model.max_output_tokens == 128_000
    assert model.supports_thinking is True
    assert model.reasoning_efforts == ["none", "low", "medium", "high", "xhigh", "max"]
    assert model.inference_controls is not None
    assert "reasoning_effort" in model.inference_controls
    assert "reasoning_summary" in model.inference_controls
    assert "temperature" not in model.inference_controls
    assert "top_p" not in model.inference_controls


@pytest.mark.unit
@pytest.mark.asyncio
async def test_bedrock_requests_are_left_unsigned_for_aperture() -> None:
    import httpx

    provider = _ApertureBedrockProvider("http://aperture.example/bedrock")
    request = httpx.Request(
        "POST",
        "http://aperture.example/bedrock/model/us.anthropic.claude-sonnet-4-6/invoke",
        json={"messages": []},
    )

    await provider._client._prepare_request(request)

    assert "authorization" not in request.headers
    assert "x-amz-date" not in request.headers
    assert "x-amz-security-token" not in request.headers


@pytest.mark.unit
@pytest.mark.parametrize("wire_api", ["openai_responses", "openai_chat"])
def test_openai_compatible_requests_are_left_unsigned_for_aperture(wire_api: str) -> None:
    provider = ApertureProvider("http://aperture.example")

    adapter = provider._build_adapter(wire_api)  # type: ignore[arg-type]

    assert adapter._client.auth_headers == {}  # type: ignore[attr-defined]


@pytest.mark.unit
def test_anthropic_requests_are_left_unsigned_for_aperture() -> None:
    provider = ApertureProvider("http://aperture.example")

    adapter = provider._build_adapter("anthropic_messages")

    assert adapter._client.auth_headers == {}  # type: ignore[attr-defined]


@pytest.mark.unit
async def test_list_models_discovers_once_and_invalidation_refreshes() -> None:
    provider = ApertureProvider("http://aperture.example/")
    provider._fetch_catalog = AsyncMock(return_value=_catalog())  # type: ignore[method-assign]

    first = await provider.list_models()
    second = await provider.list_models()

    assert first == second
    assert provider._fetch_catalog.await_count == 1

    provider.invalidate_model_cache()
    await provider.list_models()
    assert provider._fetch_catalog.await_count == 2


@pytest.mark.unit
async def test_chat_and_stream_delegate_to_the_discovered_adapter() -> None:
    provider = ApertureProvider("http://aperture.example")
    provider._fetch_catalog = AsyncMock(return_value=_catalog())  # type: ignore[method-assign]
    adapter = _FakeAdapter()
    provider._build_adapter = MagicMock(return_value=adapter)  # type: ignore[method-assign]

    response = await provider.chat(
        model="openai/gpt-5.4",
        messages=[{"role": "user", "content": "hello"}],
        think=True,
    )
    events = [
        event
        async for event in provider.chat_stream(
            model="openai/gpt-5.4",
            messages=[{"role": "user", "content": "hello again"}],
        )
    ]

    assert response.message.content == "ok"
    assert isinstance(events[0], ChatDelta)
    assert provider._build_adapter.call_args.args == ("openai_responses",)
    assert adapter.chat_calls[0]["think"] is True
    assert adapter.chat_calls[0]["model"] == "openai/gpt-5.4"
    assert adapter.chat_calls[1]["model"] == "openai/gpt-5.4"


@pytest.mark.unit
async def test_reachable_gateway_without_supported_models_is_clear() -> None:
    provider = ApertureProvider("http://aperture.example")
    provider._fetch_catalog = AsyncMock(
        return_value=[
            {  # type: ignore[method-assign]
                "id": "gemini",
                "models": ["gemini-3"],
                "compatibility": {"gemini_generate_content": True},
            }
        ]
    )

    with pytest.raises(ProviderError, match="did not return any models"):
        await provider.list_models()


@pytest.mark.unit
async def test_unknown_or_revoked_model_has_actionable_error() -> None:
    provider = ApertureProvider("http://aperture.example")
    provider._fetch_catalog = AsyncMock(return_value=_catalog())  # type: ignore[method-assign]

    with pytest.raises(ProviderError, match="Refresh the model list"):
        await provider.chat(model="removed-model", messages=[])


@pytest.mark.unit
def test_discovery_combines_provider_capabilities_with_granted_models() -> None:
    providers = _provider_list({"providers": {provider["id"]: provider for provider in _catalog()}})
    enabled = _enabled_models(
        {
            "data": [
                {"id": "gpt-5.4", "metadata": {"provider": {"id": "openai"}}},
                {"id": "company-model"},
            ]
        }
    )

    assert providers is not None
    assert enabled is not None
    filtered = _filter_catalog(providers, enabled)

    assert [(provider["id"], provider["models"]) for provider in filtered] == [
        ("openai", ["gpt-5.4"]),
        ("compatible", ["company-model"]),
    ]


@pytest.mark.unit
def test_granted_model_metadata_overrides_the_fallback_catalog() -> None:
    providers = _provider_list({"providers": {provider["id"]: provider for provider in _catalog()}})
    enabled = _enabled_models({
        "data": [{
            "id": "gpt-5.4",
            "metadata": {
                "provider": {"id": "openai"},
                "context_window": 777_000,
                "max_output_tokens": 12_345,
                "supports_images": False,
                "supports_thinking": True,
                "thinking_levels": ["low", "high"],
            },
        }],
    })

    assert providers is not None
    assert enabled is not None
    models, _routes = _routes_from_catalog(_filter_catalog(providers, enabled))

    assert models[0].context_window == 777_000
    assert models[0].max_output_tokens == 12_345
    assert models[0].supports_images is False
    assert models[0].thinking_levels == ["low", "high"]
