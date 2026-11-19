"""Client for Tailscale Aperture, with automatic model and API discovery.

Aperture is a gateway rather than one wire protocol. Its ``/v1/models``
endpoint lists the models the current Tailscale identity may use, and each
entry names the request paths that model accepts. We pick the richest client
Omnideck already supports for each model, keeping protocol choices out of the
setup UX.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.parse
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from typing import Any, Literal

import aiohttp
from pydantic import BaseModel, ConfigDict, ValidationError

from .._client import ModelClient
from .._model_metadata import build_model_info
from .._types import ChatDelta, ChatResponse, ModelInfo, ProviderError
from ._anthropic import AnthropicClient
from ._openai_chat import OpenAIChatClient
from ._openai_responses import OpenAIResponsesClient

logger = logging.getLogger(__name__)

_DISCOVERY_CACHE_TTL = 300.0
_DISCOVERY_TIMEOUT = aiohttp.ClientTimeout(total=10)

WireAPI = Literal["openai_responses", "anthropic_messages", "openai_chat"]

# Request paths Aperture lists in ``supported_endpoints``, best first.
# Responses carries the richest reasoning controls, so it wins when a model
# accepts both OpenAI formats.
_ENDPOINT_APIS: tuple[tuple[str, WireAPI], ...] = (
    ("/v1/responses", "openai_responses"),
    ("/v1/messages", "anthropic_messages"),
    ("/v1/chat/completions", "openai_chat"),
)

# Aperture serves Chat Completions when an upstream enables no other format,
# so an entry without endpoint information is treated the same way.
_DEFAULT_ENDPOINTS = ("/v1/chat/completions",)

_WIRE_LABELS: dict[WireAPI, str] = {
    "openai_responses": "Responses",
    "anthropic_messages": "Anthropic Messages",
    "openai_chat": "Chat Completions",
}


class _UpstreamInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Set on passthrough upstreams, which expect the caller's own API key.
    requires_client_auth: bool = False


class _EntryMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: _UpstreamInfo | None = None


class _ModelEntry(BaseModel):
    """One ``/v1/models`` entry: a model as served by one upstream."""

    model_config = ConfigDict(extra="ignore")

    id: str
    display_name: str | None = None
    supported_endpoints: list[str] | None = None
    context_window_tokens: int | None = None
    max_output_tokens: int | None = None
    metadata: _EntryMetadata | None = None


@dataclass(frozen=True)
class _Route:
    wire_api: WireAPI
    display_name: str
    context_window: int | None
    max_output_tokens: int | None


class ApertureClient:
    """Discovers the models Tailscale Aperture exposes and routes each request.

    Aperture speaks several request formats, so this client hands each request
    to the client for the format that model uses.
    """

    def __init__(self, base_url: str) -> None:
        self._gateway_url = base_url.rstrip("/")
        self._models: list[ModelInfo] | None = None
        self._routes: dict[str, _Route] = {}
        self._discovered_at = 0.0
        self._discovery_lock = asyncio.Lock()
        self._clients: dict[WireAPI, ModelClient] = {}

    @staticmethod
    def normalize_base_url(value: str) -> str:
        """Return the gateway root, accepting common pasted URL variants."""
        candidate = value.strip()
        if "://" not in candidate:
            candidate = f"http://{candidate}"
        parsed = urllib.parse.urlparse(candidate)
        if not parsed.netloc or not parsed.hostname:
            raise ValueError("Enter a valid Aperture gateway URL")
        if parsed.username or parsed.password:
            raise ValueError("Enter an Aperture gateway URL without embedded credentials")
        path = parsed.path.rstrip("/")
        if any(path == prefix or path.startswith(f"{prefix}/") for prefix in ("/ui", "/v1", "/bedrock")):
            path = ""
        if path:
            raise ValueError("Enter the Aperture gateway root without /v1, /bedrock, or another path")
        return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


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
        model_info: ModelInfo | None = None,
    ) -> ChatResponse:
        """Route a request through the API format Aperture advertises for the model."""
        client = await self._client_for_model(model)
        return await client.chat(
            model=model,
            messages=messages,
            tools=tools,
            options=options,
            think=think,
            model_info=model_info,
        )

    async def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[Callable[..., Any]] | None = None,
        options: dict[str, Any] | None = None,
        think: bool = False,
        model_info: ModelInfo | None = None,
    ) -> AsyncGenerator[ChatDelta | ChatResponse, None]:
        """Stream through the API format Aperture advertises for the model."""
        client = await self._client_for_model(model)
        async for event in client.chat_stream(
            model=model,
            messages=messages,
            tools=tools,
            options=options,
            think=think,
            model_info=model_info,
        ):
            yield event

    def invalidate_model_cache(self) -> None:
        """Drop discovery and the per-format clients' caches."""
        self._models = None
        self._routes.clear()
        self._discovered_at = 0.0
        for client in self._clients.values():
            client.invalidate_model_cache()

    async def _client_for_model(self, model: str) -> ModelClient:
        await self._ensure_discovered()
        route = self._routes.get(model)
        if route is None:
            raise ProviderError(
                f"Model {model!r} is not available through a supported API on this Aperture gateway. "
                "Refresh the model list and check your Aperture grants."
            )
        client = self._clients.get(route.wire_api)
        if client is None:
            client = self._build_client(route.wire_api)
            self._clients[route.wire_api] = client
        return client

    def _build_client(self, wire_api: WireAPI) -> ModelClient:
        if wire_api == "openai_responses":
            return OpenAIResponsesClient(
                base_url=f"{self._gateway_url}/v1",
                send_authorization=False,
            )
        if wire_api == "openai_chat":
            return OpenAIChatClient(
                base_url=f"{self._gateway_url}/v1",
                send_authorization=False,
            )
        if wire_api == "anthropic_messages":
            return AnthropicClient(
                base_url=self._gateway_url,
                send_authorization=False,
            )
        raise AssertionError(f"Unhandled Aperture wire API: {wire_api}")

    async def _ensure_discovered(self) -> None:
        now = time.monotonic()
        if self._models is not None and now - self._discovered_at < _DISCOVERY_CACHE_TTL:
            return
        async with self._discovery_lock:
            now = time.monotonic()
            if self._models is not None and now - self._discovered_at < _DISCOVERY_CACHE_TTL:
                return
            entries = await self._fetch_models()
            routes = _routes_from_entries(entries)
            if not routes:
                endpoints = sorted({
                    endpoint
                    for entry in entries
                    for endpoint in entry.supported_endpoints or _DEFAULT_ENDPOINTS
                })
                detail = f" Advertised endpoints: {', '.join(endpoints)}." if endpoints else ""
                raise ProviderError(
                    "Aperture is reachable, but it did not return any models using an API format "
                    f"Omnideck supports.{detail}"
                )
            self._models = [_model_info(model, route) for model, route in routes.items()]
            self._routes = routes
            self._discovered_at = time.monotonic()

    async def _fetch_models(self) -> list[_ModelEntry]:
        try:
            async with aiohttp.ClientSession(timeout=_DISCOVERY_TIMEOUT) as session:
                payload = await self._get_json(session, "/v1/models")
        except ProviderError:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise ProviderError(
                "Could not reach Aperture. Make sure Tailscale is connected and the gateway URL is reachable "
                "from Omnideck.",
                retryable=True,
                cause=exc,
            ) from exc

        entries = _model_entries(payload)
        if entries is None:
            raise ProviderError("Aperture returned an unexpected model catalog.")
        if not entries:
            raise ProviderError(
                "Aperture is reachable, but this Tailscale identity has no granted models. "
                "Check the gateway's model grants."
            )
        return entries

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


def _model_entries(payload: Any) -> list[_ModelEntry] | None:
    """Parse ``/v1/models``, skipping malformed entries."""
    raw = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return None
    entries: list[_ModelEntry] = []
    for item in raw:
        try:
            entry = _ModelEntry.model_validate(item)
        except ValidationError:
            logger.warning("Skipping malformed Aperture model entry")
            continue
        if entry.id.strip():
            entries.append(entry)
    return entries


def _wire_api(endpoints: set[str]) -> WireAPI | None:
    for endpoint, wire_api in _ENDPOINT_APIS:
        if endpoint in endpoints:
            return wire_api
    return None


def _smallest_limit(values: list[int | None]) -> int | None:
    """Return the tightest positive limit, since any upstream may serve the request."""
    reported = [value for value in values if value is not None and value > 0]
    return min(reported) if reported else None


def _routes_from_entries(entries: list[_ModelEntry]) -> dict[str, _Route]:
    """Merge entries that share a model id into one route per model.

    The same model can be served by several upstreams. Requests send the bare
    id and Aperture picks the upstream, so each model is listed once with the
    formats any of its upstreams accept and the limits all of them can honor.
    """
    by_model: dict[str, list[_ModelEntry]] = {}
    for entry in entries:
        upstream = entry.metadata.provider if entry.metadata else None
        if upstream and upstream.requires_client_auth:
            # Omnideck never sends a key to the gateway, so these cannot work.
            continue
        by_model.setdefault(entry.id.strip(), []).append(entry)

    routes: dict[str, _Route] = {}
    for model, served in by_model.items():
        endpoints = {
            endpoint
            for entry in served
            for endpoint in (
                entry.supported_endpoints
                if entry.supported_endpoints is not None
                else _DEFAULT_ENDPOINTS
            )
        }
        wire_api = _wire_api(endpoints)
        if wire_api is None:
            continue
        routes[model] = _Route(
            wire_api=wire_api,
            display_name=next((entry.display_name for entry in served if entry.display_name), model),
            context_window=_smallest_limit([entry.context_window_tokens for entry in served]),
            max_output_tokens=_smallest_limit([entry.max_output_tokens for entry in served]),
        )
    return routes


def _model_info(model: str, route: _Route) -> ModelInfo:
    # Aperture reports limits but not features, so thinking and image support
    # come from the known-model catalog.
    discovered: dict[str, int] = {}
    if route.context_window:
        discovered["context_window"] = route.context_window
    if route.max_output_tokens:
        discovered["max_output_tokens"] = route.max_output_tokens
    info = build_model_info(
        model,
        route.wire_api,
        discovered,
        display_name=route.display_name,
        wire_api=_WIRE_LABELS[route.wire_api],
        is_cloud=True,
    )
    capabilities = [
        name
        for name, supported in (("vision", info.supports_images), ("thinking", info.supports_thinking))
        if supported
    ]
    return info.model_copy(update={"capabilities": capabilities})
