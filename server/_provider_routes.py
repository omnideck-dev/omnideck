"""HTTP route handlers for the providers API.

Four handlers:

- ``GET /api/providers`` — list configured providers (direct + brokered).
- ``POST /api/providers`` — add/configure a provider. For direct kinds
  (Ollama, no-auth OpenAI-compatible) writes to ``settings.direct_providers``;
  for brokered kinds creates an ``llm_<name>`` model-provider connection via the
  supervisor. Probes the new provider and returns its model list (503 on
  unreachable); nothing persists on a failed probe.
- ``PATCH /api/providers/{name}`` — update connection details for an
  existing provider, re-probing afterward.
- ``DELETE /api/providers/{name}`` — remove. Drops the settings entry for
  a direct provider or asks the supervisor to remove the brokered connection for
  a brokered one.

A brokered provider's api_key lives only in the supervisor's encrypted vault,
but its base_url (not a secret) is also cached in
``settings.brokered_provider_urls`` so the settings UI can show and edit it
without a vault round-trip — kept in sync by ``_set_brokered_url`` on every
add/update/remove.
"""

from __future__ import annotations

import json
import logging
import re

from aiohttp import web
from pydantic import BaseModel, ConfigDict, ValidationError

from brokering.supervisor_client import SupervisorError
from providers import get_provider, probe_direct_provider, reset_provider
from server._brokering import supervisor_call as _supervisor_call
from settings import _validate_base_url, load_settings, save_settings

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


def _unreachable_response(name: str, exc: Exception) -> web.Response:
    """503 payload for a failed provider probe, shared by add and update."""
    return web.json_response(
        {
            "error": "provider_unreachable",
            "message": _sanitize(str(exc)),
            "provider": name,
        },
        status=503,
    )


def _set_brokered_url(name: str, base_url: str | None) -> None:
    """Sync the display-only base_url cache for a brokered provider."""
    settings = load_settings()
    urls = dict(settings.get("brokered_provider_urls") or {})
    if base_url:
        urls[name] = base_url
    elif name in urls:
        del urls[name]
    else:
        return
    save_settings({"brokered_provider_urls": urls})


async def _brokered_provider_connections() -> list[dict[str, object]]:
    """Read model-provider records from their supervisor domain."""
    result = await _supervisor_call("list", {"kind": "model_provider"})
    return list(result["connections"])


async def _remove_brokered_connection(connection_id: object) -> None:
    """Best-effort teardown of a model-provider connection by id.

    Used to roll back a brokered add whose post-create probe failed, so
    "Test & add" never leaves a zombie connection behind. Errors are logged,
    not raised — the caller already has the real error (probe failure) to
    report, and a rollback failure shouldn't mask it.
    """
    if not isinstance(connection_id, str) or not connection_id:
        return
    try:
        await _supervisor_call("remove", {"id": connection_id})
    except (FileNotFoundError, ConnectionRefusedError, OSError, SupervisorError) as exc:
        logger.warning(
            "failed to roll back provider connection %r after failed probe: %s",
            connection_id, exc,
        )


# ── GET ──────────────────────────────────────────────────────────────────


async def handle_list_providers(_request: web.Request) -> web.Response:
    """Return configured LLM providers.

    Direct-connect providers (Ollama, no-auth OpenAI-compatible) come from
    ``settings.direct_providers``; brokered providers come from singleton
    ``llm_<name>`` model-provider connections in the supervisor.
    """
    settings = load_settings()
    brokered_urls = settings.get("brokered_provider_urls") or {}

    providers: list[dict[str, object]] = []

    for name, entry in (settings.get("direct_providers") or {}).items():
        providers.append({
            "name": name,
            "label": _label(name),
            "kind": "direct",
            "base_url": entry.get("base_url"),
            "status": "configured",
        })

    brokered_available = True
    try:
        connections = await _brokered_provider_connections()
    except (FileNotFoundError, ConnectionRefusedError, OSError, SupervisorError) as exc:
        # Direct providers remain usable even when the broker supervisor is
        # temporarily down. The response flag lets a future UI surface the
        # partial view without turning the whole Providers page into a 500.
        logger.warning("brokered providers unavailable while listing: %s", exc)
        connections = []
        brokered_available = False
    for connection in connections:
        slug = connection.get("slug")
        if not isinstance(slug, str) or not slug.startswith("llm_"):
            continue
        name = slug.removeprefix("llm_")
        providers.append({
            "name": name,
            "label": _label(name),
            "kind": "brokered",
            "base_url": brokered_urls.get(name),
            "status": connection.get("state") or "running",
        })

    return web.json_response({
        "providers": providers,
        "brokered_available": brokered_available,
    })


# ── POST ─────────────────────────────────────────────────────────────────


class _AddProviderBody(BaseModel):
    """Schema for ``POST /api/providers``."""

    model_config = ConfigDict(extra="forbid")

    name: str
    base_url: str | None = None
    api_key: str | None = None


async def handle_add_provider(request: web.Request) -> web.Response:
    """Configure a provider, probe it, return its model list.

    Storage choice is implicit: ``api_key`` present → brokered (model-provider
    connection via the supervisor); absent → direct (``settings.direct_providers``
    entry).

    A failed probe must not leave a provider behind. For a direct provider
    that's straightforward — probe a throwaway instance before writing
    settings. A brokered provider can only be probed through its broker
    process, which the supervisor's ``add`` verb must create first; on a
    failed probe that connection is torn down again before returning, so
    the net effect is the same as the direct path: nothing persists.
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

    if spec.api_key:
        # Brokered: create the llm_<name> model-provider connection, then
        # probe it. A failed probe rolls the connection back.
        auth_blob: dict[str, str] = {"api_key": spec.api_key}
        if spec.base_url:
            # OpenAI-compat with a key needs the upstream URL stored alongside
            # the key so the broker knows where to forward. Validate it the
            # same as a direct provider's — this one reaches a real network
            # host too, so it needs the same blocked-host guard.
            try:
                _validate_base_url(spec.base_url)
            except ValueError as exc:
                return web.json_response({"error": str(exc)}, status=400)
            auth_blob["base_url"] = spec.base_url
        try:
            added = await _supervisor_call("add", {
                "slug": f"llm_{name}",
                "kind": "model_provider",
                "label": _label(name),
                "auth_blob": auth_blob,
            })
        except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
            logger.warning("supervisor unreachable for provider add: %s", exc)
            return web.json_response(
                {"error": "Integrations service isn't running."},
                status=503,
            )
        except SupervisorError as exc:
            return web.json_response({"error": _sanitize(exc.message)}, status=400)

        reset_provider(name)
        try:
            models = await get_provider(name).list_models()
        except Exception as exc:  # noqa: BLE001 - any failure here is "couldn't reach"
            reset_provider(name)
            await _remove_brokered_connection(added.get("id"))
            return _unreachable_response(name, exc)
        _set_brokered_url(name, spec.base_url)
        kind = "brokered"
        stored_base_url = spec.base_url
    else:
        # Direct: probe a throwaway instance first, only persist on success.
        if not spec.base_url:
            return web.json_response(
                {"error": "base_url is required when no api_key is provided"},
                status=400,
            )
        try:
            _validate_base_url(spec.base_url)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        try:
            models = await probe_direct_provider(name, spec.base_url)
        except Exception as exc:  # noqa: BLE001 - any failure here is "couldn't reach"
            return _unreachable_response(name, exc)
        settings = load_settings()
        direct = dict(settings.get("direct_providers") or {})
        direct[name] = {"base_url": spec.base_url}
        save_settings({"direct_providers": direct})
        reset_provider(name)
        kind = "direct"
        stored_base_url = spec.base_url

    return web.json_response(
        {
            "provider": {
                "name": name,
                "label": _label(name),
                "kind": kind,
                "base_url": stored_base_url,
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

    try:
        connections = await _brokered_provider_connections()
    except (FileNotFoundError, ConnectionRefusedError, OSError, SupervisorError) as exc:
        logger.warning("supervisor unreachable for provider remove lookup: %s", exc)
        return web.json_response(
            {"error": "Integrations service isn't running."},
            status=503,
        )
    target_slug = f"llm_{name}"
    for connection in connections:
        if connection.get("slug") == target_slug:
            try:
                await _supervisor_call("remove", {"id": connection.get("id")})
            except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
                logger.warning("supervisor unreachable for provider remove: %s", exc)
                return web.json_response(
                    {"error": "Integrations service isn't running."},
                    status=503,
                )
            except SupervisorError as exc:
                return web.json_response({"error": _sanitize(exc.message)}, status=400)
            _set_brokered_url(name, None)
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

    For a direct provider, probes the candidate URL first and only
    rewrites its ``settings.direct_providers`` entry on success — the same
    probe-before-persist shape as ``POST /api/providers``. For a brokered
    one, the supervisor transactionally replaces its credentials and process
    while retaining the previous connection on failure, then this is probed
    the same way an add is. The response shape matches ``POST /api/providers``
    either way.
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
        # Direct kind — probe the candidate URL before persisting, same
        # probe-before-persist shape as the add path, so a typo doesn't
        # overwrite a working entry with an unreachable one.
        if not spec.base_url:
            return web.json_response(
                {"error": "base_url is required to update a direct provider"},
                status=400,
            )
        try:
            _validate_base_url(spec.base_url)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        try:
            models = await probe_direct_provider(name, spec.base_url)
        except Exception as exc:  # noqa: BLE001 - any failure here is "couldn't reach"
            return _unreachable_response(name, exc)
        direct[name] = {"base_url": spec.base_url}
        save_settings({"direct_providers": direct})
        reset_provider(name)
        kind = "direct"
        stored_base_url: str | None = spec.base_url
    else:
        # Brokered kind — must currently exist as an llm_<name> integration.
        try:
            connections = await _brokered_provider_connections()
        except (FileNotFoundError, ConnectionRefusedError, OSError, SupervisorError) as exc:
            logger.warning("supervisor unreachable for provider update lookup: %s", exc)
            return web.json_response(
                {"error": "Integrations service isn't running."},
                status=503,
            )
        target_slug = f"llm_{name}"
        existing = next(
            (connection for connection in connections if connection.get("slug") == target_slug),
            None,
        )
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
        if "base_url" in spec.model_fields_set:
            # Sent explicitly — including an empty string to clear it — so
            # honor it as-is instead of falling back to the cached value.
            new_base_url = spec.base_url or None
        else:
            new_base_url = (settings.get("brokered_provider_urls") or {}).get(name)
        if new_base_url:
            try:
                _validate_base_url(new_base_url)
            except ValueError as exc:
                return web.json_response({"error": str(exc)}, status=400)
        auth_blob: dict[str, str] = {"api_key": spec.api_key}
        if new_base_url:
            auth_blob["base_url"] = new_base_url
        # Credential replacement is transactional in the supervisor for
        # process-level failures: if the replacement broker cannot start,
        # the prior encrypted credentials and live broker are restored
        # before this request fails. It does not validate the credentials
        # against the real upstream provider first, though — that's what
        # the probe below is for, and a failure there can't be rolled back
        # the same way (tracked separately, not fixed here).
        try:
            await _supervisor_call("reconnect", {
                "id": existing.get("id"),
                "kind": "model_provider",
                "auth_blob": auth_blob,
            })
        except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
            logger.warning("supervisor unreachable for provider update: %s", exc)
            return web.json_response(
                {"error": "Integrations service isn't running."},
                status=503,
            )
        except SupervisorError as exc:
            return web.json_response({"error": _sanitize(exc.message)}, status=400)
        _set_brokered_url(name, new_base_url)
        reset_provider(name)
        try:
            models = await get_provider(name).list_models()
        except Exception as exc:  # noqa: BLE001 - any failure here is "couldn't reach"
            return _unreachable_response(name, exc)
        kind = "brokered"
        stored_base_url = new_base_url

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
