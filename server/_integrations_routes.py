"""HTTP routes under ``/api/integrations`` — CRUD for integrations.

No auth layer on these routes today: the app server + supervisor run in the
same container, and the supervisor's ``app.sock`` is already group-gated to
the ``omnideck`` UID at the filesystem level. HTTP-level auth is a separate
concern handled by the frontend.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from aiohttp import web

from config import load_config
from integrations import supervisor_client
from integrations.catalog import (
    integration_catalog,
    model_provider_catalog,
)
from integrations.operations import operation_descriptors
from integrations.supervisor_client import SupervisorError
from server._integrations_http import error_response
from tools.integrations import mark_added, mark_removed

logger = logging.getLogger(__name__)


# Sanitize-only — turn arbitrary characters into the [a-z0-9_-] set the
# supervisor's regex demands. The supervisor still validates the result.
_SUFFIX_NON_ALLOWED = re.compile(r"[^a-z0-9_-]")
_SUFFIX_DASH_RUNS = re.compile(r"-+")


def _derive_suffix_from_email(auth_blob: dict[str, Any] | None) -> str | None:
    """Sanitize ``auth_blob['email']``'s local-part into a usable user suffix.

    Returns ``None`` if there's no email or the cleaned local-part is empty.
    The supervisor enforces the actual format invariant — this is just here
    so the frontend can submit credentials without thinking up an ID.
    """
    if not isinstance(auth_blob, dict):
        return None
    email = auth_blob.get("email")
    if not isinstance(email, str):
        return None
    return _sanitize_suffix(email.split("@", 1)[0])


def _derive_connection_suffix(
    auth_blob: dict[str, Any] | None,
    label: str | None,
) -> str | None:
    """Derive a stable local ID suffix without requiring an auth schema.

    Existing email integrations retain their historical email-local-part IDs.
    Integrations with other credential shapes fall back to their user-visible
    label, which keeps MCP, environment-variable, and future brokers out of
    provider-specific branches in this generic route.
    """
    return _derive_suffix_from_email(auth_blob) or (
        _sanitize_suffix(label) if isinstance(label, str) else None
    )


def _sanitize_suffix(raw: str) -> str | None:
    """Reduce arbitrary text to the supervisor's ``[a-z0-9_-]`` suffix set.

    Returns ``None`` if nothing usable survives. The supervisor enforces the
    actual format invariant — this just spares the frontend from inventing IDs.
    """
    cleaned = _SUFFIX_DASH_RUNS.sub(
        "-", _SUFFIX_NON_ALLOWED.sub("-", raw.lower()),
    ).strip("-")
    return cleaned[:48] or None


async def _supervisor_call(verb: str, args: dict[str, Any]) -> dict[str, Any]:
    """Call a supervisor verb with a 90s timeout.

    A transactional replacement can wait on a 30s broker READY handshake and,
    on failure, another 30s handshake while restoring the prior broker. Ninety
    seconds gives that rollback headroom while still bounding a wedged
    supervisor. ``TimeoutError`` is an ``OSError`` subclass on 3.11+, so route
    handlers catch it through the ``except OSError`` arm and return a 503.
    """
    app_sock = load_config().integrations.app_sock_path
    return await asyncio.wait_for(
        supervisor_client.call(verb, args, app_sock_path=app_sock),
        timeout=90.0,
    )


async def handle_list_integrations(_request: web.Request) -> web.Response:
    """``GET /api/integrations`` — non-secret metadata for every active integration."""
    try:
        result = await _supervisor_call("list", {"kind": "integration"})
    except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
        logger.warning("supervisor unreachable for list: %s", exc)
        return web.json_response(
            {"error": {"code": "UNAVAILABLE", "message": "Integrations service isn't running."}},
            status=503,
        )
    except SupervisorError as exc:
        return error_response(exc.code, exc.message)
    return web.json_response(result)


async def handle_integration_catalog(_request: web.Request) -> web.Response:
    """Return the safe, authoritative native integration catalog projection."""
    entries = []
    for entry in integration_catalog().values():
        operation_ids = entry.operations | frozenset().union(*entry.scope_operations.values())
        public_entry = {
            "id": entry.slug,
            "title": entry.title,
            "description": entry.description,
            "category": entry.category,
            "kind": entry.kind,
            "operations": operation_descriptors(operation_ids),
        }
        operation_groups = [
            {
                "id": group.id,
                "title": group.title,
                "operation_ids": sorted(group.operation_ids & operation_ids),
            }
            for group in entry.operation_groups
            if group.operation_ids & operation_ids
        ]
        if operation_groups:
            public_entry["operation_groups"] = operation_groups
        entries.append(public_entry)
    return web.json_response({"integrations": entries})


async def handle_add_integration(request: web.Request) -> web.Response:
    """``POST /api/integrations`` — register a new integration.

    Request body (JSON)::

        {
          "slug": "icloud",
          "label": "iCloud — Larry",
          "auth_blob": {"email": "...", "password": "..."},
          "operation_grants": ["email.messages.search", "email.messages.send"]
        }

    The integration ID's local suffix is derived by this handler before
    forwarding to the supervisor; clients do not pick it. Existing email
    credentials use their local part for compatibility, while every other
    credential shape falls back to the connection label.

    On success: ``201 Created`` with ``{id, socket}`` (the broker's UDS path,
    for debugging — callers normally don't touch it directly).
    """
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response(
            {"error": {"code": "BAD_REQUEST",
                       "message": "Couldn't read that request. Refresh and try again."}},
            status=400,
        )
    if not isinstance(body, dict):
        return web.json_response(
            {"error": {"code": "BAD_REQUEST",
                       "message": "Couldn't read that request. Refresh and try again."}},
            status=400,
        )

    # Keep integration IDs deterministic and out of the user's mental model.
    # Email remains the compatibility-preferred hint, but it is not a generic
    # integration requirement.
    slug = body.get("slug", "")
    if slug in model_provider_catalog():
        return error_response(
            "BAD_REQUEST", "Model providers must be configured through the Providers API.",
        )
    body["kind"] = "integration"
    label = body.get("label")
    derived = _derive_connection_suffix(
        body.get("auth_blob"),
        label if isinstance(label, str) else None,
    )
    if not derived:
        return error_response(
            "BAD_REQUEST", "A label is required to name this integration.",
        )
    body["user_suffix"] = derived

    try:
        result = await _supervisor_call("add", body)
    except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
        logger.warning("supervisor unreachable for add: %s", exc)
        return web.json_response(
            {"error": {"code": "UNAVAILABLE", "message": "Integrations service isn't running."}},
            status=503,
        )
    except SupervisorError as exc:
        return error_response(exc.code, exc.message)

    # Update the app-server's tool-visibility cache so the agent sees the new
    # integration's tools on the next turn without a supervisor round-trip.
    # The supervisor's add response carries everything the cache needs (id,
    # slug, operation grants). Missing id/slug is a supervisor bug — surface it
    # as 502 rather than returning 201 with a corrupted cache.
    integration_id = result.get("id")
    slug = result.get("slug")
    if not (isinstance(integration_id, str) and isinstance(slug, str)):
        logger.error("supervisor add response missing id/slug: %r", result)
        return error_response("UPSTREAM", "Something went wrong on our end. Try again.")
    grants_result = result.get("operation_grants")
    mark_added(
        integration_id,
        slug,
        frozenset(grants_result) if isinstance(grants_result, list) else frozenset(),
        result.get("state") or "running",
    )

    return web.json_response(result, status=201)


async def handle_update_integration(request: web.Request) -> web.Response:
    """``PATCH /api/integrations/{id}`` — update mutable fields on an integration.

    Body fields (each optional, at least one required): ``operation_grants``
    (array of canonical operation IDs) and ``label`` (non-empty string).
    The deprecated ``permissions`` object is also accepted for older clients,
    but cannot be combined with ``operation_grants``. Grant changes respawn the
    broker; updating ``label`` is metadata-only.

    On success: ``200 OK`` with the updated record. On unknown id: ``404``.
    """
    integration_id = request.match_info.get("id", "")
    if not integration_id:
        return error_response(
            "BAD_REQUEST",
            "Couldn't tell which integration to update. Refresh and try again.",
        )

    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response(
            {"error": {"code": "BAD_REQUEST",
                       "message": "Couldn't read that request. Refresh and try again."}},
            status=400,
        )
    if not isinstance(body, dict):
        return error_response(
            "BAD_REQUEST",
            "Couldn't read that request. Refresh and try again.",
        )

    rpc_args: dict[str, Any] = {"id": integration_id}
    if "operation_grants" in body and "permissions" in body:
        return error_response(
            "BAD_REQUEST", "Choose individual tools or legacy permissions, not both.",
        )
    if "operation_grants" in body:
        if not isinstance(body["operation_grants"], list) or any(
            not isinstance(item, str) for item in body["operation_grants"]
        ):
            return error_response("BAD_REQUEST", "Selected tools must be an array of IDs.")
        rpc_args["operation_grants"] = body["operation_grants"]
    if "permissions" in body:
        if not isinstance(body["permissions"], dict):
            return error_response("BAD_REQUEST", "Permissions must be an object.")
        rpc_args["permissions"] = body["permissions"]
    if "label" in body:
        if not isinstance(body["label"], str) or not body["label"].strip():
            return error_response("BAD_REQUEST", "Label can't be empty.")
        rpc_args["label"] = body["label"]
    if not ({"operation_grants", "permissions", "label"} & rpc_args.keys()):
        return error_response("BAD_REQUEST", "Nothing to update.")

    try:
        result = await _supervisor_call("update", rpc_args)
    except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
        logger.warning("supervisor unreachable for update: %s", exc)
        return web.json_response(
            {"error": {"code": "UNAVAILABLE", "message": "Integrations service isn't running."}},
            status=503,
        )
    except SupervisorError as exc:
        return error_response(exc.code, exc.message)

    grants_result = result.get("operation_grants")
    mark_added(
        integration_id,
        result.get("slug") or "",
        frozenset(grants_result) if isinstance(grants_result, list) else frozenset(),
        result.get("state") or "running",
    )
    return web.json_response(result)


async def handle_remove_integration(request: web.Request) -> web.Response:
    """``DELETE /api/integrations/{id}`` — tear down a registered integration.

    Calls the supervisor's ``remove`` verb, which SIGTERMs the broker and
    deletes the vault files. On success the app server clears its tool-
    visibility cache entry so the agent's next turn no longer sees tools
    bound to this integration.

    On success: ``204 No Content``. On unknown id: ``404``.
    """
    integration_id = request.match_info.get("id", "")
    if not integration_id:
        return error_response(
            "BAD_REQUEST",
            "Couldn't tell which integration to remove. Refresh and try again.",
        )

    try:
        await _supervisor_call("remove", {"id": integration_id})
    except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
        logger.warning("supervisor unreachable for remove: %s", exc)
        return web.json_response(
            {"error": {"code": "UNAVAILABLE", "message": "Integrations service isn't running."}},
            status=503,
        )
    except SupervisorError as exc:
        return error_response(exc.code, exc.message)

    mark_removed(integration_id)
    return web.Response(status=204)


async def handle_reconnect_integration(request: web.Request) -> web.Response:
    """Replace one integration's credentials without changing its identity."""
    integration_id = request.match_info.get("id", "")
    if not integration_id:
        return error_response("BAD_REQUEST", "Couldn't tell which integration to reconnect.")
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return error_response("BAD_REQUEST", "Couldn't read that request. Refresh and try again.")
    if not isinstance(body, dict) or not isinstance(body.get("auth_blob"), dict):
        return error_response("BAD_REQUEST", "Connection credentials are required.")
    try:
        result = await _supervisor_call("reconnect", {
            "id": integration_id,
            "kind": "integration",
            "auth_blob": body["auth_blob"],
        })
    except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
        logger.warning("supervisor unreachable for reconnect: %s", exc)
        return web.json_response(
            {"error": {"code": "UNAVAILABLE", "message": "Integrations service isn't running."}},
            status=503,
        )
    except SupervisorError as exc:
        return error_response(exc.code, exc.message)

    grants_result = result.get("operation_grants")
    mark_added(
        integration_id,
        result.get("slug") or "",
        frozenset(grants_result) if isinstance(grants_result, list) else frozenset(),
        result.get("state") or "running",
    )
    return web.json_response(result)


def register_integrations_routes(app: web.Application) -> None:
    """Register ``/api/integrations`` CRUD routes on the application."""
    app.router.add_route("GET", "/api/integrations", handle_list_integrations)
    app.router.add_route("GET", "/api/integrations/catalog", handle_integration_catalog)
    app.router.add_route("POST", "/api/integrations", handle_add_integration)
    app.router.add_route(
        "PATCH", "/api/integrations/{id}", handle_update_integration,
    )
    app.router.add_route(
        "POST", "/api/integrations/{id}/reconnect", handle_reconnect_integration,
    )
    app.router.add_route(
        "DELETE", "/api/integrations/{id}", handle_remove_integration,
    )
