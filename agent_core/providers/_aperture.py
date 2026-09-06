"""Tailscale Aperture provider with automatic upstream/API discovery.

Aperture is a gateway rather than one wire protocol.  Its ``/api/providers``
endpoint reports compatibility flags, while ``/v1/models`` reports the models
available to the current Tailscale identity.  We combine those catalogs to
select the richest adapter Omnideck already supports for each model, keeping
protocol choices out of the setup UX.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

import aiohttp

from ._anthropic import AnthropicProvider
from ._base import BaseAPIProvider
from ._models import ChatDelta, ChatResponse, LLMConfig, ModelInfo, ProviderError
from ._openai import OpenAIProvider
from ._model_metadata import (
    discovered_metadata,
    fallback_metadata,
    inference_controls as controls_for_api,
    reasoning_efforts as known_reasoning_efforts,
    thinking_configuration,
    thinking_default,
)
from ._openai_responses import OpenAIResponsesProvider
from ._protocol import Provider

logger = logging.getLogger(__name__)

_DISCOVERY_CACHE_TTL = 300.0
_DISCOVERY_TIMEOUT = aiohttp.ClientTimeout(total=10)

WireAPI = Literal[
    "openai_responses",
    "anthropic_messages",
    "bedrock_model_invoke",
    "openai_chat",
]

_WIRE_PRIORITY: dict[WireAPI, int] = {
    "openai_responses": 0,
    "anthropic_messages": 1,
    "bedrock_model_invoke": 2,
    "openai_chat": 3,
}

_WIRE_LABELS: dict[WireAPI, str] = {
    "openai_responses": "Responses",
    "anthropic_messages": "Anthropic Messages",
    "bedrock_model_invoke": "Amazon Bedrock",
    "openai_chat": "Chat Completions",
}


@dataclass(frozen=True)
class _Route:
    wire_api: WireAPI
    upstream_id: str
    upstream_name: str
    request_model: str
    metadata: dict[str, Any]


@dataclass
class _EnabledModel:
    provider_ids: set[str]
    metadata_by_provider: dict[str, dict[str, Any]]
    generic_metadata: dict[str, Any] | None = None


class _ApertureBedrockProvider(AnthropicProvider):
    """Anthropic Messages semantics over Aperture's Bedrock invoke endpoint.

    The Anthropic SDK handles Bedrock's model-specific request shape and AWS
    event-stream response framing.  Aperture authenticates the caller using
    Tailscale identity and injects its configured Bedrock bearer token, so the
    client request must remain unsigned.
    """

    def __init__(self, base_url: str) -> None:
        BaseAPIProvider.__init__(self, base_url=base_url)
        import anthropic

        class _UnsignedAsyncAnthropicBedrock(anthropic.AsyncAnthropicBedrock):
            async def _prepare_request(self, request: Any) -> None:
                # Aperture's equivalent of CLAUDE_CODE_SKIP_BEDROCK_AUTH=1:
                # do not attach a dummy SigV4 Authorization header that can be
                # forwarded instead of the gateway-managed bearer token.
                return None

        self._client = _UnsignedAsyncAnthropicBedrock(
            aws_region="us-east-1",
            base_url=base_url,
        )
        self._model_cache: list[ModelInfo] | None = None
        self._model_cache_at = 0.0


class ApertureProvider(BaseAPIProvider):
    """Provider that discovers and routes models exposed by Tailscale Aperture."""

    def __init__(self, base_url: str) -> None:
        gateway_url = base_url.rstrip("/")
        super().__init__(base_url=gateway_url)
        self._gateway_url = gateway_url
        self._models: list[ModelInfo] | None = None
        self._routes: dict[str, _Route] = {}
        self._discovered_at = 0.0
        self._discovery_lock = asyncio.Lock()
        self._adapters: dict[WireAPI, Provider] = {}

    @classmethod
    def from_config(cls, llm_config: LLMConfig) -> "ApertureProvider":
        """Construct an Aperture connection from its gateway URL."""
        if not llm_config.base_url:
            raise ValueError("Aperture requires a gateway URL")
        return cls(llm_config.base_url)

    async def list_models(self) -> list[ModelInfo]:
        """Discover models and API formats from Aperture, cached for five minutes."""
        await self._ensure_discovered()
        return list(self._models or [])

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[Callable[..., Any]] | None = None,
        options: dict[str, Any] | None = None,
        think: bool = False,
    ) -> ChatResponse:
        """Route a request through the API format Aperture advertises for the model."""
        adapter = await self._adapter_for_model(model)
        route = self._routes[model]
        return await adapter.chat(
            model=route.request_model,
            messages=messages,
            tools=tools,
            options=options,
            think=think,
        )

    async def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[Callable[..., Any]] | None = None,
        options: dict[str, Any] | None = None,
        think: bool = False,
    ) -> AsyncGenerator[ChatDelta | ChatResponse, None]:
        """Stream through the API format Aperture advertises for the model."""
        adapter = await self._adapter_for_model(model)
        route = self._routes[model]
        async for event in adapter.chat_stream(
            model=route.request_model,
            messages=messages,
            tools=tools,
            options=options,
            think=think,
        ):
            yield event

    def invalidate_model_cache(self) -> None:
        """Drop discovery and nested-adapter caches."""
        self._models = None
        self._routes.clear()
        self._discovered_at = 0.0
        for adapter in self._adapters.values():
            adapter.invalidate_model_cache()

    async def _adapter_for_model(self, model: str) -> Provider:
        await self._ensure_discovered()
        route = self._routes.get(model)
        if route is None:
            raise ProviderError(
                f"Model {model!r} is not available through a supported API on this Aperture gateway. "
                "Refresh the model list and check your Aperture grants."
            )
        adapter = self._adapters.get(route.wire_api)
        if adapter is None:
            adapter = self._build_adapter(route.wire_api)
            self._adapters[route.wire_api] = adapter
        return adapter

    def _build_adapter(self, wire_api: WireAPI) -> Provider:
        if wire_api == "openai_responses":
            return OpenAIResponsesProvider(
                base_url=f"{self._gateway_url}/v1",
                send_authorization=False,
            )
        if wire_api == "openai_chat":
            return OpenAIProvider(
                base_url=f"{self._gateway_url}/v1",
                send_authorization=False,
            )
        if wire_api == "anthropic_messages":
            return AnthropicProvider(base_url=self._gateway_url, send_authorization=False)
        if wire_api == "bedrock_model_invoke":
            return _ApertureBedrockProvider(base_url=f"{self._gateway_url}/bedrock")
        raise AssertionError(f"Unhandled Aperture wire API: {wire_api}")

    async def _ensure_discovered(self) -> None:
        now = time.monotonic()
        if self._models is not None and now - self._discovered_at < _DISCOVERY_CACHE_TTL:
            return
        async with self._discovery_lock:
            now = time.monotonic()
            if self._models is not None and now - self._discovered_at < _DISCOVERY_CACHE_TTL:
                return
            catalog = await self._fetch_catalog()
            models, routes = _routes_from_catalog(catalog)
            if not models:
                flags = sorted(
                    {flag for upstream in catalog for flag, enabled in _compatibility(upstream).items() if enabled}
                )
                detail = f" Advertised API formats: {', '.join(flags)}." if flags else ""
                raise ProviderError(
                    "Aperture is reachable, but it did not return any models using an API format "
                    f"Omnideck supports.{detail}"
                )
            self._models = models
            self._routes = routes
            self._discovered_at = time.monotonic()

    async def _fetch_catalog(self) -> list[dict[str, Any]]:
        try:
            async with aiohttp.ClientSession(timeout=_DISCOVERY_TIMEOUT) as session:
                providers_payload, models_payload = await asyncio.gather(
                    self._get_json(session, "/api/providers"),
                    self._get_json(session, "/v1/models"),
                )
        except ProviderError:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise ProviderError(
                "Could not reach Aperture. Make sure Tailscale is connected and the gateway URL is reachable "
                "from Omnideck.",
                retryable=True,
                cause=exc,
            ) from exc

        providers = _provider_list(providers_payload)
        if providers is None:
            raise ProviderError("Aperture returned an unexpected provider catalog.")
        enabled_models = _enabled_models(models_payload)
        if enabled_models is None:
            raise ProviderError("Aperture returned an unexpected model catalog.")
        if not enabled_models:
            raise ProviderError(
                "Aperture is reachable, but this Tailscale identity has no granted models. "
                "Check the gateway's model grants."
            )
        return _filter_catalog(providers, enabled_models)

    async def _get_json(self, session: aiohttp.ClientSession, path: str) -> Any:
        async with session.get(f"{self._gateway_url}{path}") as response:
            body = await response.text()
            if response.status < 200 or response.status >= 300:
                if response.status == 403:
                    message = "Aperture denied this Tailscale identity. Check the gateway's model grants."
                else:
                    message = f"Aperture discovery failed at {path} with HTTP {response.status}."
                raise ProviderError(
                    message,
                    retryable=response.status in {408, 429, 500, 502, 503, 504},
                    status_code=response.status,
                )
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise ProviderError("Aperture returned an invalid discovery response.", cause=exc) from exc


def _provider_list(payload: Any) -> list[dict[str, Any]] | None:
    if isinstance(payload, dict):
        payload = payload.get("providers")
        if isinstance(payload, dict):
            payload = [{"id": provider_id, **item} for provider_id, item in payload.items() if isinstance(item, dict)]
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        return None
    return cast(list[dict[str, Any]], payload)


def _enabled_models(payload: Any) -> dict[str, _EnabledModel] | None:
    """Map each granted model id to explicit provider ids, when supplied."""
    if isinstance(payload, dict):
        payload = payload.get("data")
    if not isinstance(payload, list):
        return None
    enabled: dict[str, _EnabledModel] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        model = item.get("id")
        if not isinstance(model, str) or not model:
            continue
        granted = enabled.setdefault(model, _EnabledModel(set(), {}))
        metadata = item.get("metadata")
        provider = metadata.get("provider") if isinstance(metadata, dict) else None
        provider_id = provider.get("id") if isinstance(provider, dict) else None
        if isinstance(provider_id, str) and provider_id:
            granted.provider_ids.add(provider_id)
            granted.metadata_by_provider[provider_id] = item
        else:
            granted.generic_metadata = item
    return enabled


def _filter_catalog(
    catalog: list[dict[str, Any]],
    enabled_models: dict[str, _EnabledModel],
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for upstream in catalog:
        upstream_id = str(upstream.get("id") or "").strip()
        raw_models = upstream.get("models")
        if not isinstance(raw_models, list):
            continue
        granted_models = [
            (model, enabled_models[model])
            for model in raw_models
            if isinstance(model, str)
            and model in enabled_models
            and (
                not enabled_models[model].provider_ids
                or upstream_id in enabled_models[model].provider_ids
            )
        ]
        if granted_models:
            filtered.append({
                **upstream,
                "models": [model for model, _granted in granted_models],
                "model_metadata": {
                    model: granted.metadata_by_provider.get(upstream_id)
                    or granted.generic_metadata
                    or {}
                    for model, granted in granted_models
                },
            })
    return filtered


def _compatibility(upstream: dict[str, Any]) -> dict[str, bool]:
    raw = upstream.get("compatibility")
    if not isinstance(raw, dict):
        return {"openai_chat": True}
    values = {str(key): bool(value) for key, value in raw.items()}
    if not values:
        # Aperture's default when no explicit compatibility flag is enabled.
        values["openai_chat"] = True
    return values


def _select_wire_api(compatibility: dict[str, bool], model: str) -> WireAPI | None:
    if compatibility.get("openai_responses"):
        return "openai_responses"
    if compatibility.get("anthropic_messages"):
        return "anthropic_messages"
    if compatibility.get("bedrock_model_invoke") and _is_anthropic_bedrock_model(model):
        return "bedrock_model_invoke"
    if compatibility.get("openai_chat"):
        return "openai_chat"
    return None


def _is_anthropic_bedrock_model(model: str) -> bool:
    lowered = model.lower()
    return "anthropic" in lowered or "claude" in lowered


def _routes_from_catalog(catalog: list[dict[str, Any]]) -> tuple[list[ModelInfo], dict[str, _Route]]:
    routes: dict[str, _Route] = {}

    for upstream in catalog:
        upstream_id = str(upstream.get("id") or "").strip()
        upstream_name = str(upstream.get("name") or upstream_id or "Aperture").strip()
        compatibility = _compatibility(upstream)
        raw_models = upstream.get("models")
        raw_model_metadata = upstream.get("model_metadata")
        model_metadata = raw_model_metadata if isinstance(raw_model_metadata, dict) else {}
        if not isinstance(raw_models, list):
            continue
        for raw_model in raw_models:
            if not isinstance(raw_model, str) or not raw_model.strip():
                continue
            model = raw_model.strip()
            wire_api = _select_wire_api(compatibility, model)
            if wire_api is None:
                continue
            exposed_model = f"{upstream_id}/{model}" if upstream_id else model
            candidate = _Route(
                wire_api=wire_api,
                upstream_id=upstream_id,
                upstream_name=upstream_name,
                # Aperture supports provider-qualified ids in JSON bodies. APIs
                # with the model embedded in the URL path require the bare id.
                request_model=model if wire_api == "bedrock_model_invoke" else exposed_model,
                metadata=discovered_metadata(model_metadata.get(model)),
            )
            current = routes.get(exposed_model)
            if current is None or _WIRE_PRIORITY[candidate.wire_api] < _WIRE_PRIORITY[current.wire_api]:
                routes[exposed_model] = candidate

    models = [_model_info(model, route) for model, route in routes.items()]
    return models, routes


def _model_info(model: str, route: _Route) -> ModelInfo:
    display_name = model.removeprefix(f"{route.upstream_id}/") if route.upstream_id else model
    meta = fallback_metadata(display_name)
    discovered = route.metadata
    context_window = discovered.get("context_window", meta.get("context_window"))
    max_output_tokens = discovered.get("max_output_tokens", meta.get("max_output_tokens"))
    supports_images = bool(discovered.get("supports_images", meta.get("supports_images", False)))
    supports_thinking = bool(discovered.get("supports_thinking", meta.get("supports_thinking", False)))
    inference_controls: list[str]
    reasoning_efforts: list[str] | None = None

    if route.wire_api in {"openai_responses", "openai_chat"}:
        inference_controls = controls_for_api(route.wire_api, supports_thinking)
        if supports_thinking:
            reasoning_efforts = discovered.get("thinking_levels") or known_reasoning_efforts(display_name)
    elif route.wire_api in {"anthropic_messages", "bedrock_model_invoke"}:
        inference_controls = controls_for_api(route.wire_api, supports_thinking)
    else:  # pragma: no cover - WireAPI is exhaustive
        inference_controls = []

    thinking_control, thinking_levels, thinking_required = thinking_configuration(
        route.wire_api, display_name, supports_thinking,
    )
    if discovered.get("thinking_control"):
        thinking_control = discovered["thinking_control"]
    if discovered.get("thinking_levels"):
        thinking_levels = discovered["thinking_levels"]
    if "thinking_required" in discovered:
        thinking_required = discovered["thinking_required"]
    inference_controls = controls_for_api(
        route.wire_api,
        supports_thinking,
        thinking_control,
        model_id=display_name,
        supported_parameters=discovered.get("supported_parameters"),
    )

    capabilities: list[str] = []
    if supports_images:
        capabilities.append("vision")
    if supports_thinking:
        capabilities.append("thinking")

    return ModelInfo(
        name=model,
        display_name=display_name,
        context_window=context_window,
        max_output_tokens=max_output_tokens,
        supports_images=supports_images,
        supports_thinking=supports_thinking,
        upstream_provider=route.upstream_name,
        wire_api=_WIRE_LABELS[route.wire_api],
        inference_api=route.wire_api,
        inference_controls=inference_controls,
        thinking_control=thinking_control,
        thinking_levels=thinking_levels,
        thinking_default=discovered.get("thinking_default") or thinking_default(
            display_name, thinking_control, thinking_levels,
        ),
        thinking_required=thinking_required,
        reasoning_efforts=reasoning_efforts,
        capabilities=capabilities,
        is_cloud=True,
    )
