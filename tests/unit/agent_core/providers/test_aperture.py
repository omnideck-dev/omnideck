"""Tests for Tailscale Aperture discovery and protocol routing."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_core.providers._aperture import (
    ApertureProvider,
    _model_entries,
    _model_info,
    _routes_from_entries,
)
from agent_core.providers import ChatDelta, ChatMessage, ChatResponse, ProviderError


def _entry(
    model: str,
    upstream: str,
    endpoints: list[str] | None,
    **fields: Any,
) -> dict[str, Any]:
    """Build a ``/v1/models`` entry shaped like a real Aperture response."""
    entry: dict[str, Any] = {
        "id": model,
        "object": "model",
        "metadata": {
            "provider": {
                "id": upstream,
                "name": upstream.title(),
                "description": "",
                "requires_client_auth": False,
                "upstream": "default",
            },
        },
        "owned_by": "ts-llm-proxy",
        **fields,
    }
    if endpoints is not None:
        entry["supported_endpoints"] = endpoints
    return entry


def _payload() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            _entry(
                "claude-haiku-5-5", "cheap-anthropic", ["/v1/messages"],
                display_name="Claude Haiku 5.5",
                context_window_tokens=1_000_000,
                max_output_tokens=128_000,
            ),
            _entry(
                "claude-haiku-5-5", "expensive-anthropic", ["/v1/messages"],
                display_name="Claude Haiku 5.5",
                context_window_tokens=200_000,
                max_output_tokens=64_000,
            ),
            _entry("gpt-5.4", "openai", ["/v1/responses", "/v1/chat/completions"]),
            _entry("us.moonshotai.kimi-k3", "bedrock-open-weight", ["/v1/chat/completions"]),
            _entry("gemini-3", "gemini", ["/v1beta/models/gemini-3:generateContent"]),
        ],
    }


def _provider_with_payload(payload: dict[str, Any]) -> ApertureProvider:
    provider = ApertureProvider("http://aperture.example")
    provider._get_json = AsyncMock(return_value=payload)  # type: ignore[method-assign]
    return provider


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
def test_each_model_uses_the_best_endpoint_it_supports() -> None:
    entries = _model_entries(_payload())
    assert entries is not None

    routes = _routes_from_entries(entries)

    assert routes["claude-haiku-5-5"].wire_api == "anthropic_messages"
    assert routes["gpt-5.4"].wire_api == "openai_responses"
    assert routes["us.moonshotai.kimi-k3"].wire_api == "openai_chat"


@pytest.mark.unit
def test_models_with_only_unsupported_endpoints_are_hidden() -> None:
    entries = _model_entries(_payload())
    assert entries is not None

    routes = _routes_from_entries(entries)

    assert "gemini-3" not in routes


@pytest.mark.unit
def test_model_served_by_two_upstreams_is_listed_once_with_the_tighter_limits() -> None:
    entries = _model_entries(_payload())
    assert entries is not None

    routes = _routes_from_entries(entries)

    haiku = routes["claude-haiku-5-5"]
    assert list(routes).count("claude-haiku-5-5") == 1
    assert haiku.display_name == "Claude Haiku 5.5"
    assert haiku.context_window == 200_000
    assert haiku.max_output_tokens == 64_000


@pytest.mark.unit
def test_model_uses_responses_when_any_upstream_offers_it() -> None:
    entries = _model_entries({
        "data": [
            _entry("gpt-5.4", "chat-only", ["/v1/chat/completions"]),
            _entry("gpt-5.4", "full", ["/v1/responses", "/v1/chat/completions"]),
        ],
    })
    assert entries is not None

    routes = _routes_from_entries(entries)

    assert routes["gpt-5.4"].wire_api == "openai_responses"


@pytest.mark.unit
def test_entry_without_endpoints_defaults_to_chat_completions() -> None:
    entries = _model_entries({"data": [_entry("company-model", "internal", None)]})
    assert entries is not None

    routes = _routes_from_entries(entries)

    assert routes["company-model"].wire_api == "openai_chat"


@pytest.mark.unit
def test_upstreams_that_need_the_callers_own_key_are_hidden() -> None:
    passthrough = _entry("gpt-5.4", "passthrough", ["/v1/responses"])
    passthrough["metadata"]["provider"]["requires_client_auth"] = True
    entries = _model_entries({"data": [passthrough]})
    assert entries is not None

    routes = _routes_from_entries(entries)

    assert routes == {}


@pytest.mark.unit
def test_malformed_entries_are_skipped() -> None:
    entries = _model_entries({
        "data": [
            "not-an-object",
            {"supported_endpoints": ["/v1/messages"]},
            {"id": "   "},
            _entry("gpt-5.4", "openai", ["/v1/responses"]),
        ],
    })

    assert entries is not None
    assert [entry.id for entry in entries] == ["gpt-5.4"]


@pytest.mark.unit
def test_unexpected_catalog_shape_is_rejected() -> None:
    assert _model_entries({"providers": []}) is None
    assert _model_entries(["gpt-5.4"]) is None


@pytest.mark.unit
async def test_model_list_prefers_gateway_limits_and_names() -> None:
    provider = _provider_with_payload(_payload())

    models = {model.name: model for model in await provider.list_models()}

    haiku = models["claude-haiku-5-5"]
    assert haiku.display_name == "Claude Haiku 5.5"
    assert haiku.context_window == 200_000
    assert haiku.max_output_tokens == 64_000
    assert haiku.inference_api == "anthropic_messages"
    assert haiku.wire_api == "Anthropic Messages"


@pytest.mark.unit
async def test_model_list_fills_missing_details_from_the_known_model_catalog() -> None:
    provider = _provider_with_payload({
        "data": [_entry("gpt-5.6-luna", "openai", ["/v1/responses", "/v1/chat/completions"])],
    })

    [model] = await provider.list_models()

    assert model.display_name == "gpt-5.6-luna"
    assert model.inference_api == "openai_responses"
    assert model.context_window == 1_050_000
    assert model.max_output_tokens == 128_000
    assert model.supports_thinking is True
    assert model.thinking_levels == ["none", "low", "medium", "high", "xhigh", "max"]
    assert model.inference_controls is not None
    assert "reasoning_effort" in model.inference_controls
    assert "reasoning_summary" in model.inference_controls
    assert "temperature" not in model.inference_controls


@pytest.mark.unit
def test_anthropic_model_gets_anthropic_thinking_levels() -> None:
    entries = _model_entries({"data": [_entry("claude-sonnet-5-5", "anthropic", ["/v1/messages"])]})
    assert entries is not None
    routes = _routes_from_entries(entries)

    model = _model_info("claude-sonnet-5-5", routes["claude-sonnet-5-5"])

    assert model.inference_api == "anthropic_messages"
    assert model.thinking_control == "reasoning_effort"
    assert model.thinking_levels == ["low", "medium", "high", "xhigh", "max"]
    assert model.thinking_default == "high"


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
async def test_discovery_reads_only_the_model_list() -> None:
    provider = _provider_with_payload(_payload())

    await provider.list_models()

    paths = [call.args[1] for call in provider._get_json.await_args_list]  # type: ignore[attr-defined]
    assert paths == ["/v1/models"]


@pytest.mark.unit
async def test_list_models_discovers_once_and_invalidation_refreshes() -> None:
    provider = _provider_with_payload(_payload())

    first = await provider.list_models()
    second = await provider.list_models()

    assert first == second
    assert provider._get_json.await_count == 1  # type: ignore[attr-defined]

    provider.invalidate_model_cache()
    await provider.list_models()
    assert provider._get_json.await_count == 2  # type: ignore[attr-defined]


@pytest.mark.unit
async def test_chat_and_stream_send_the_bare_model_id() -> None:
    provider = _provider_with_payload(_payload())
    adapter = _FakeAdapter()
    provider._build_adapter = MagicMock(return_value=adapter)  # type: ignore[method-assign]

    response = await provider.chat(
        model="claude-haiku-5-5",
        messages=[{"role": "user", "content": "hello"}],
        think=True,
    )
    events = [
        event
        async for event in provider.chat_stream(
            model="claude-haiku-5-5",
            messages=[{"role": "user", "content": "hello again"}],
        )
    ]

    assert response.message.content == "ok"
    assert isinstance(events[0], ChatDelta)
    assert provider._build_adapter.call_args.args == ("anthropic_messages",)
    assert adapter.chat_calls[0]["think"] is True
    assert adapter.chat_calls[0]["model"] == "claude-haiku-5-5"
    assert adapter.chat_calls[1]["model"] == "claude-haiku-5-5"


@pytest.mark.unit
async def test_reachable_gateway_without_supported_models_is_clear() -> None:
    provider = _provider_with_payload({
        "data": [_entry("gemini-3", "gemini", ["/v1beta/models/gemini-3:generateContent"])],
    })

    with pytest.raises(ProviderError, match="did not return any models") as excinfo:
        await provider.list_models()

    assert "/v1beta/models/gemini-3:generateContent" in str(excinfo.value)


@pytest.mark.unit
async def test_identity_without_granted_models_is_clear() -> None:
    provider = _provider_with_payload({"object": "list", "data": []})

    with pytest.raises(ProviderError, match="no granted models"):
        await provider.list_models()


@pytest.mark.unit
async def test_unexpected_catalog_is_clear() -> None:
    provider = _provider_with_payload({"providers": []})

    with pytest.raises(ProviderError, match="unexpected model catalog"):
        await provider.list_models()


@pytest.mark.unit
async def test_unknown_or_revoked_model_has_actionable_error() -> None:
    provider = _provider_with_payload(_payload())

    with pytest.raises(ProviderError, match="Refresh the model list"):
        await provider.chat(model="removed-model", messages=[])


@pytest.mark.unit
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ai.example.ts.net", "http://ai.example.ts.net"),
        ("http://ai.example.ts.net:8080/", "http://ai.example.ts.net:8080"),
        ("http://ai.example.ts.net/ui/", "http://ai.example.ts.net"),
        ("http://ai.example.ts.net/ui/chat/providers", "http://ai.example.ts.net"),
        ("http://ai.example.ts.net/v1", "http://ai.example.ts.net"),
        ("http://ai.example.ts.net/v1/models", "http://ai.example.ts.net"),
        ("http://ai.example.ts.net/bedrock", "http://ai.example.ts.net"),
    ],
)
def test_gateway_url_accepts_common_gateway_forms(value: str, expected: str) -> None:
    assert ApertureProvider.normalize_base_url(value) == expected


@pytest.mark.unit
def test_gateway_url_rejects_unknown_path() -> None:
    with pytest.raises(ValueError, match="gateway root"):
        ApertureProvider.normalize_base_url("http://ai.example.ts.net/something-else")


@pytest.mark.unit
def test_gateway_url_rejects_embedded_credentials() -> None:
    with pytest.raises(ValueError, match="without embedded credentials"):
        ApertureProvider.normalize_base_url("http://user:secret@ai.example.ts.net")


@pytest.mark.unit
@pytest.mark.parametrize(("model", "wire_api"), [
    ("claude-haiku-5-5", "anthropic_messages"),
    ("gpt-5.4", "openai_responses"),
    ("us.moonshotai.kimi-k3", "openai_chat"),
])
async def test_requests_use_the_details_aperture_listed(model: str, wire_api: str) -> None:
    provider = _provider_with_payload(_payload())
    listed = {info.name: info for info in await provider.list_models()}

    adapter = provider._build_adapter(wire_api)  # type: ignore[arg-type]

    assert adapter._listed_model(model) is listed[model]  # type: ignore[attr-defined]
