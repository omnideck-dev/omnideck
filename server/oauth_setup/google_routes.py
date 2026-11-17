"""Google-specific request validation; lifecycle belongs to the shared coordinator."""

import json

from aiohttp import web

from integrations.catalog import integration_catalog
from server._integrations_http import error_response
from .adapters.google import GoogleOAuthAdapter
from .models import NewConnection, Reconnect
from .routes import GOOGLE_CALLBACK_PATH, SETUP_KEY

_GOOGLE_IDENTITY_SCOPES = frozenset({"openid", "email", "profile"})


class _StringRequired(ValueError):
    """Raised by :func:`_require_str` when a key is missing or non-string."""


# Maps internal field names to the user-facing label that appears in
# error messages. Keeps validation copy in plain language ("Email
# address") rather than leaking implementation field names ("auth_blob.email").
_FIELD_LABEL = {
    "client_id": "Client ID",
    "client_secret": "Client Secret",
    "label": "Label",
    "slug": "Provider",
    "user_suffix": "Account suffix",
}


def _require_str(body: dict, key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        label = _FIELD_LABEL.get(key, key.replace("_", " ").capitalize())
        msg = f"{label} can't be empty."
        raise _StringRequired(msg)
    return value


async def start(request: web.Request) -> web.Response:
    """Validate Google settings and start one app-owned authorization task."""
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

    try:
        slug = _require_str(body, "slug")
    except _StringRequired as exc:
        return error_response("BAD_REQUEST", str(exc))
    catalog_entry = integration_catalog().get(slug)
    if catalog_entry is None or not catalog_entry.scope_operations:
        return error_response(
            "BAD_REQUEST",
            "This integration does not support OAuth setup.",
        )

    scopes = body.get("scopes")
    if not isinstance(scopes, list) or not all(
        isinstance(s, str) and s for s in scopes
    ):
        return error_response(
            "BAD_REQUEST", "Provider access is required before authorizing.",
        )
    unsupported_scopes = set(scopes).difference(
        _GOOGLE_IDENTITY_SCOPES,
        catalog_entry.scope_operations,
    )
    if unsupported_scopes:
        return error_response(
            "BAD_REQUEST",
            "The requested provider access is not supported by this integration.",
        )

    # Build the redirect URI from the request's host so it always points
    # back to *this* instance — whether the user is on localhost:9090
    # (manual-test), 127.0.0.1:8080 (dev), or any other configuration.
    # Google's Desktop-app client type accepts any http://localhost or
    # http://127.0.0.1 URL without needing the specific port pre-registered.
    redirect_uri = f"{request.scheme}://{request.host}{GOOGLE_CALLBACK_PATH}"

    grants_raw = body.get("operation_grants")
    if grants_raw is not None and (
        not isinstance(grants_raw, list)
        or any(not isinstance(item, str) for item in grants_raw)
    ):
        return error_response("BAD_REQUEST", "Selected tools must be an array of IDs.")
    if "permissions" in body or "write_allowed" in body:
        return error_response(
            "BAD_REQUEST", "This screen is out of date. Refresh the app, then try again.",
        )
    reconnect_id = body.get("reconnect_id")
    if reconnect_id is not None and (
        not isinstance(reconnect_id, str) or not reconnect_id
    ):
        return error_response("BAD_REQUEST", "Connection to reconnect is invalid.")

    try:
        adapter = GoogleOAuthAdapter(
            client_id=_require_str(body, "client_id"),
            client_secret=_require_str(body, "client_secret"), scopes=scopes,
        )
        label = _require_str(body, "label")
        target: NewConnection | Reconnect
        if reconnect_id is not None:
            target = Reconnect(reconnect_id)
        else:
            target = NewConnection(slug, label, _require_str(body, "user_suffix"), tuple(grants_raw or []))
        pending = await request.app[SETUP_KEY].start(adapter, target, redirect_uri=redirect_uri)
    except _StringRequired as exc:
        return error_response("BAD_REQUEST", str(exc))
    except ValueError as exc:
        return error_response("BAD_REQUEST", str(exc))

    return web.json_response({**pending.public_status(), "authorize_url": pending.browser.authorize_url},
                             headers={"Cache-Control": "no-store"})
