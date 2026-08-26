"""HTTP route handlers for the providers API.

Three handlers:

- ``GET /api/providers`` — list configured providers (direct + brokered).
- ``POST /api/providers`` — add/configure a provider. For direct kinds
  (Ollama, no-auth OpenAI-compatible) writes to ``settings.direct_providers``;
  for brokered kinds creates an ``llm_<name>`` vault integration via the
  supervisor. Probes the new provider and returns its model list (503 on
  unreachable).
- ``DELETE /api/providers/{name}`` — remove. Drops the settings entry for
  a direct provider or asks the supervisor to remove the integration for
  a brokered one.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from aiohttp import web
from pydantic import BaseModel, ConfigDict, ValidationError

from integrations.supervisor_client import SupervisorError
from sdk.providers import reset_provider
from sdk.providers._anthropic import AnthropicProvider
from sdk.providers._models import ModelInfo, ProviderError
from sdk.providers._ollama import OllamaProvider
from sdk.providers._openai import OpenAIProvider
from sdk.providers._openai_responses import OpenAIResponsesProvider
from server._integrations_routes import _supervisor_call
from settings import _validate_base_url, load_settings, save_settings
from tools.integrations import registered_integrations
from tools.integrations._state import refresh_registered_integrations

logger = logging.getLogger(__name__)

# Provider catalog. The five names the rest of the app recognizes; anything
# else gets rejected at add time.
_KNOWN_PROVIDERS: set[str] = {
    "ollama",
    "openai",
    "anthropic",
    "openrouter",
    "openai_compat",
}

# Provider name → display label. Used for the integration's ``label`` field
# on brokered creates and for surfacing the provider in the UI.
_PROVIDER_LABELS: dict[str, str] = {
    "ollama": "Ollama",
    "openai": "OpenAI API",
    "anthropic": "Anthropic API",
    "openrouter": "OpenRouter",
    "openai_compat": "OpenAI-compatible",
}

# SDK-facing defaults for cloud providers when probing before the broker
# exists. Catalog static_env uses bare upstream hosts (the proxy joins the
# client's /v1 path); here the OpenAI client needs the /v1 suffix itself.
_DEFAULT_PROBE_BASE_URLS: dict[str, str | None] = {
    "openai": "https://api.openai.com/v1",
    "anthropic": None,  # Anthropic SDK default
    "openrouter": "https://openrouter.ai/api/v1",
}

# Non-secret mirror of user-supplied brokered base URLs (openai_compat with
# a key). Secrets stay in the vault; this is only so GET / edit can show URL.
_BROKERED_BASE_URLS_KEY = "brokered_base_urls"

# Patterns that could contain credentials — scrubbed before the message
# leaves the process. Same shape as the model routes' sanitizer.
_KEY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-[A-Za-z0-9_-]{10,}"), "sk-***"),
    (re.compile(r"Bearer\s+\S+", re.IGNORECASE), "Bearer ***"),
]

# A wrong URL often lands on a reverse proxy or captive portal that answers
# with an HTML error page, and the client hands that page back as the error
# string. Detect the markup so we can collapse it instead of dumping it.
_HTML_RE = re.compile(r"<\s*(?:!doctype|html|head|body|title|center|h1)\b", re.IGNORECASE)
_STATUS_CODE_RE = re.compile(r"\(status code:\s*(\d{3})\)")


def _sanitize(msg: str) -> str:
    for pattern, replacement in _KEY_PATTERNS:
        msg = pattern.sub(replacement, msg)
    # Collapse a raw HTML page to one line, keeping the HTTP status if present.
    if _HTML_RE.search(msg):
        status = _STATUS_CODE_RE.search(msg)
        suffix = f" (HTTP {status.group(1)})" if status else ""
        return f"The server returned an unexpected response{suffix}."
    return msg


def _label(name: str) -> str:
    return _PROVIDER_LABELS.get(name, name)


def _brokered_base_urls() -> dict[str, str]:
    raw = load_settings().get(_BROKERED_BASE_URLS_KEY) or {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}


def _set_brokered_base_url(name: str, base_url: str | None) -> None:
    urls = _brokered_base_urls()
    if base_url:
        urls[name] = base_url
    else:
        urls.pop(name, None)
    save_settings({_BROKERED_BASE_URLS_KEY: urls})


def _clear_brokered_base_url(name: str) -> None:
    urls = _brokered_base_urls()
    if name not in urls:
        return
    urls.pop(name, None)
    save_settings({_BROKERED_BASE_URLS_KEY: urls})


def _ephemeral_provider(
    name: str,
    *,
    base_url: str | None,
    api_key: str | None,
) -> Any:
    """Build a one-shot provider that talks upstream without vault/settings.

    Used to probe credentials before persisting them so a failed "Test & add"
    leaves no orphan configuration.
    """
    if name == "ollama":
        return OllamaProvider(host=base_url)
    if name == "openai":
        return OpenAIResponsesProvider(
            api_key=api_key,
            base_url=base_url or _DEFAULT_PROBE_BASE_URLS["openai"],
        )
    if name == "anthropic":
        return AnthropicProvider(
            api_key=api_key,
            base_url=base_url or _DEFAULT_PROBE_BASE_URLS["anthropic"],
        )
    if name == "openrouter":
        return OpenAIProvider(
            api_key=api_key,
            base_url=base_url or _DEFAULT_PROBE_BASE_URLS["openrouter"],
        )
    if name == "openai_compat":
        return OpenAIProvider(api_key=api_key, base_url=base_url)
    msg = f"Unknown provider: {name!r}"
    raise ValueError(msg)


async def _probe_models(
    name: str,
    *,
    base_url: str | None,
    api_key: str | None,
) -> list[ModelInfo] | web.Response:
    """Probe upstream; return models or a 503 JSON response."""
    try:
        provider = _ephemeral_provider(name, base_url=base_url, api_key=api_key)
        return await provider.list_models()
    except ProviderError as exc:
        return web.json_response(
            {
                "error": "provider_unreachable",
                "message": _sanitize(str(exc)),
                "provider": name,
            },
            status=503,
        )
    except Exception as exc:  # noqa: BLE001 - any failure here is "couldn't reach"
        return web.json_response(
            {
                "error": "provider_unreachable",
                "message": _sanitize(str(exc)),
                "provider": name,
            },
            status=503,
        )


# ── GET ──────────────────────────────────────────────────────────────────


async def handle_list_providers(_request: web.Request) -> web.Response:
    """Return configured LLM providers.

    Direct-connect providers (Ollama, no-auth OpenAI-compatible) come from
    ``settings.direct_providers``; brokered providers come from the
    integrations supervisor (singleton ``llm_<name>`` integrations).

    The supervisor is the source of truth for brokered integrations; the
    app-side cache can lag a mutation done through this same module, so
    refresh it before reading. One extra RPC per Providers-page load.
    """
    settings = load_settings()

    providers: list[dict[str, object]] = []

    for name, entry in (settings.get("direct_providers") or {}).items():
        providers.append({
            "name": name,
            "label": _label(name),
            "kind": "direct",
            "base_url": entry.get("base_url"),
            "status": "configured",
        })

    brokered_urls = _brokered_base_urls()
    await refresh_registered_integrations()
    integrations = await registered_integrations()
    for ri in integrations.values():
        if not ri.slug.startswith("llm_"):
            continue
        name = ri.slug.removeprefix("llm_")
        providers.append({
            "name": name,
            "label": _label(name),
            "kind": "brokered",
            "base_url": brokered_urls.get(name),
            "status": ri.state,
        })

    return web.json_response({"providers": providers})


# ── POST ─────────────────────────────────────────────────────────────────


class _AddProviderBody(BaseModel):
    """Schema for ``POST /api/providers``."""

    model_config = ConfigDict(extra="forbid")

    name: str
    base_url: str | None = None
    api_key: str | None = None


async def handle_add_provider(request: web.Request) -> web.Response:
    """Configure a provider only after a successful upstream probe.

    Storage choice is implicit: ``api_key`` present → brokered (vault
    integration); absent → direct (``settings.direct_providers`` entry).
    The endpoint is probed with the supplied URL/key first; nothing is
    written until that probe succeeds, so a failed "Test & add" leaves no
    orphan configuration.
    """
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response({"error": "Invalid JSON"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "Request body must be a JSON object"}, status=400)
    try:
        spec = _AddProviderBody(**body)
    except ValidationError as exc:
        logger.warning("invalid /api/providers body: %s", exc)
        return web.json_response({"error": "Unknown or invalid field"}, status=400)

    name = spec.name
    if name not in _KNOWN_PROVIDERS:
        return web.json_response(
            {"error": f"Unknown provider: {name!r}. "
                     f"Choose one of: {sorted(_KNOWN_PROVIDERS)}"},
            status=400,
        )

    brokered = bool(spec.api_key)
    base_url = spec.base_url

    if not brokered:
        if not base_url:
            return web.json_response(
                {"error": "base_url is required when no api_key is provided"},
                status=400,
            )
        try:
            _validate_base_url(base_url)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
    elif name == "openai_compat":
        # Brokered openai-compat still needs the upstream URL alongside the key.
        if not base_url:
            return web.json_response(
                {"error": "base_url is required for openai_compat"},
                status=400,
            )
        try:
            _validate_base_url(base_url)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
    elif base_url:
        try:
            _validate_base_url(base_url)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)

    probed = await _probe_models(name, base_url=base_url, api_key=spec.api_key)
    if isinstance(probed, web.Response):
        return probed
    models = probed

    if brokered:
        auth_blob: dict[str, str] = {"api_key": spec.api_key or ""}
        if base_url:
            # OpenAI-compat with a key needs the upstream URL stored alongside
            # the key so the broker knows where to forward.
            auth_blob["base_url"] = base_url
        try:
            await _supervisor_call("add", {
                "slug": f"llm_{name}",
                "label": _label(name),
                "auth_blob": auth_blob,
                "permissions": {},
                "write_allowed": False,
            })
        except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
            logger.warning("supervisor unreachable for provider add: %s", exc)
            return web.json_response(
                {"error": "Integrations service isn't running."},
                status=503,
            )
        except SupervisorError as exc:
            return web.json_response({"error": _sanitize(exc.message)}, status=400)
        if base_url:
            _set_brokered_base_url(name, base_url)
    else:
        settings = load_settings()
        direct = dict(settings.get("direct_providers") or {})
        direct[name] = {"base_url": base_url}
        save_settings({"direct_providers": direct})

    # Force the next get_provider(name) to re-build against the new config.
    reset_provider(name)

    return web.json_response(
        {
            "provider": {
                "name": name,
                "label": _label(name),
                "kind": "brokered" if brokered else "direct",
                "base_url": base_url if (not brokered or base_url) else None,
                "status": "connected",
            },
            "models": [m.model_dump() for m in models],
        },
        status=201,
    )


# ── DELETE ───────────────────────────────────────────────────────────────


async def handle_remove_provider(request: web.Request) -> web.Response:
    """Remove a provider.

    For a direct provider the settings entry is dropped; for a brokered
    one the supervisor's ``remove`` RPC tears down the broker process and
    deletes the vault entry. Returns 404 if the name doesn't match any
    configured provider.
    """
    name = request.match_info["name"]
    if name not in _KNOWN_PROVIDERS:
        return web.json_response({"error": f"Unknown provider: {name!r}"}, status=400)

    settings = load_settings()
    direct = dict(settings.get("direct_providers") or {})
    if name in direct:
        del direct[name]
        save_settings({"direct_providers": direct})
        reset_provider(name)
        return web.json_response({"ok": True})

    integrations = await registered_integrations()
    target_slug = f"llm_{name}"
    for ri in integrations.values():
        if ri.slug == target_slug:
            try:
                await _supervisor_call("remove", {"id": ri.id})
            except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
                logger.warning("supervisor unreachable for provider remove: %s", exc)
                return web.json_response(
                    {"error": "Integrations service isn't running."},
                    status=503,
                )
            except SupervisorError as exc:
                return web.json_response({"error": _sanitize(exc.message)}, status=400)
            _clear_brokered_base_url(name)
            reset_provider(name)
            return web.json_response({"ok": True})

    return web.json_response({"error": f"Provider {name!r} is not configured"}, status=404)


# ── PATCH ────────────────────────────────────────────────────────────────


class _UpdateProviderBody(BaseModel):
    """Schema for ``PATCH /api/providers/{name}``."""

    model_config = ConfigDict(extra="forbid")

    base_url: str | None = None
    api_key: str | None = None


async def handle_update_provider(request: web.Request) -> web.Response:
    """Update an existing provider's connection details.

    For a direct provider, rewrites its ``settings.direct_providers``
    entry (and validates the new URL). For a brokered one, the supervisor
    has no auth_blob-aware update verb yet, so the change is implemented
    as remove + add server-side — keeping the operation atomic from the
    client's perspective. Credentials are probed first so a bad URL/key
    does not replace a working configuration. Response shape matches
    ``POST /api/providers``.
    """
    name = request.match_info["name"]
    if name not in _KNOWN_PROVIDERS:
        return web.json_response({"error": f"Unknown provider: {name!r}"}, status=400)
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response({"error": "Invalid JSON"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "Request body must be a JSON object"}, status=400)
    try:
        spec = _UpdateProviderBody(**body)
    except ValidationError as exc:
        logger.warning("invalid PATCH /api/providers body: %s", exc)
        return web.json_response({"error": "Unknown or invalid field"}, status=400)

    settings = load_settings()
    direct = dict(settings.get("direct_providers") or {})

    if name in direct:
        # Direct kind — update the base_url.
        if not spec.base_url:
            return web.json_response(
                {"error": "base_url is required to update a direct provider"},
                status=400,
            )
        try:
            _validate_base_url(spec.base_url)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)

        probed = await _probe_models(name, base_url=spec.base_url, api_key=None)
        if isinstance(probed, web.Response):
            return probed
        models = probed

        direct[name] = {"base_url": spec.base_url}
        save_settings({"direct_providers": direct})
        kind = "direct"
        stored_base_url: str | None = spec.base_url
    else:
        # Brokered kind — must currently exist as an llm_<name> integration.
        integrations = await registered_integrations()
        target_slug = f"llm_{name}"
        existing = next((ri for ri in integrations.values() if ri.slug == target_slug), None)
        if existing is None:
            return web.json_response(
                {"error": f"Provider {name!r} is not configured"},
                status=404,
            )
        if not spec.api_key:
            return web.json_response(
                {"error": "api_key is required to update a brokered provider"},
                status=400,
            )

        # Prefer the newly supplied URL; fall back to the non-secret mirror
        # so key-only rotations keep the previous openai_compat base URL.
        base_url = spec.base_url or _brokered_base_urls().get(name)
        if name == "openai_compat" and not base_url:
            return web.json_response(
                {"error": "base_url is required to update openai_compat"},
                status=400,
            )
        if base_url:
            try:
                _validate_base_url(base_url)
            except ValueError as exc:
                return web.json_response({"error": str(exc)}, status=400)

        probed = await _probe_models(name, base_url=base_url, api_key=spec.api_key)
        if isinstance(probed, web.Response):
            return probed
        models = probed

        auth_blob: dict[str, str] = {"api_key": spec.api_key}
        if base_url:
            auth_blob["base_url"] = base_url
        # Atomic-ish: remove, then add with the new auth_blob. The supervisor
        # doesn't currently expose an auth_blob-aware update verb; revisit
        # when it does. Probe above keeps a failed update from replacing a
        # working config.
        try:
            await _supervisor_call("remove", {"id": existing.id})
            await _supervisor_call("add", {
                "slug": target_slug,
                "label": _label(name),
                "auth_blob": auth_blob,
                "permissions": {},
                "write_allowed": False,
            })
        except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
            logger.warning("supervisor unreachable for provider update: %s", exc)
            return web.json_response(
                {"error": "Integrations service isn't running."},
                status=503,
            )
        except SupervisorError as exc:
            return web.json_response({"error": _sanitize(exc.message)}, status=400)
        if base_url:
            _set_brokered_base_url(name, base_url)
        kind = "brokered"
        stored_base_url = base_url

    reset_provider(name)

    return web.json_response({
        "provider": {
            "name": name,
            "label": _label(name),
            "kind": kind,
            "base_url": stored_base_url,
            "status": "connected",
        },
        "models": [m.model_dump() for m in models],
    })


def register_provider_routes(app: web.Application) -> None:
    """Register provider API routes."""
    app.router.add_route("GET", "/api/providers", handle_list_providers)
    app.router.add_route("POST", "/api/providers", handle_add_provider)
    app.router.add_route("PATCH", "/api/providers/{name}", handle_update_provider)
    app.router.add_route("DELETE", "/api/providers/{name}", handle_remove_provider)
