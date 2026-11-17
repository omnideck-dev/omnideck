"""MCP setup routes; provider tokens never cross the browser boundary."""

import json
import secrets
import re

from aiohttp import web

from integrations.catalog import integration_catalog
from integrations.catalog.slack import SLACK_MCP_ENDPOINT, SLACK_MCP_ISSUER, SLACK_MCP_SCOPES, slack_app_manifest
from server._brokering import supervisor_call
from server._integrations_http import error_response
from .adapters.mcp import MCPOAuthAdapter
from .models import NewConnection, Reconnect
from .routes import SETUP_KEY, MCP_REDIRECT_KEY


async def connection_settings(request: web.Request) -> web.Response:
    redirect_uri = request.app[MCP_REDIRECT_KEY]
    settings = {"redirect_uri": redirect_uri, "slack_manifest": slack_app_manifest(redirect_uri)}
    if connection_id := request.query.get("connection_id"):
        try:
            settings["connection"] = await supervisor_call("mcp_setup_settings", {"id": connection_id})
        except Exception:
            return error_response("UPSTREAM", "Could not load the saved sign-in settings. Close setup and try again.")
    return web.json_response(settings, headers={"Cache-Control": "no-store"})


async def start(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Connection settings are required.")
        allowed = {"slug", "label", "endpoint", "client_id", "issuer", "scopes", "reconnect_id"}
        if set(body) - allowed or any(not isinstance(value, str) or len(value) > 4096 for value in body.values()):
            raise ValueError("Invalid connection settings.")
        entry = integration_catalog().get(body.get("slug", ""))
        if entry is None or entry.driver_id != "remote.mcp":
            raise ValueError("Choose an MCP integration.")
        if not body.get("label", "").strip():
            raise ValueError("Connection name is required.")
        if entry.slug == "slack":
            # An organization supplies its public client ID. Endpoint, issuer
            # and scope policy remain pinned; no shared development identity.
            if set(body) - {"slug", "label", "client_id", "reconnect_id"}:
                raise ValueError("Slack sign-in settings cannot be overridden.")
            client_id = body.get("client_id", "").strip()
            if not re.fullmatch(r"[0-9]+\.[0-9]+", client_id):
                return error_response("BAD_REQUEST", "Enter the Client ID from your internal Slack app’s Basic Information page.")
            body.update(endpoint=SLACK_MCP_ENDPOINT, issuer=SLACK_MCP_ISSUER,
                        client_id=client_id, scopes=" ".join(SLACK_MCP_SCOPES))
        elif not body.get("endpoint"):
            raise ValueError("Server URL is required.")
        if body.get("reconnect_id"):
            records = await supervisor_call("list", {"kind": "integration"})
            existing = next((item for item in records["connections"] if item["id"] == body["reconnect_id"]), None)
            if existing is None or existing["slug"] != entry.slug:
                raise ValueError("The integration to reconnect was not found.")
        target = (Reconnect(body["reconnect_id"]) if body.get("reconnect_id") else
                  NewConnection(entry.slug, body["label"], secrets.token_hex(8), ()))
        pending = await request.app[SETUP_KEY].start(
            MCPOAuthAdapter(body), target,
            redirect_uri=request.app[MCP_REDIRECT_KEY],
        )
    except (ValueError, json.JSONDecodeError):
        return error_response("BAD_REQUEST", "Check the connection settings and try again.")
    except Exception:
        return error_response("UPSTREAM", "Could not start sign-in. Check the server and retry.")
    return web.json_response({**pending.public_status(), "authorize_url": pending.browser.authorize_url}, headers={"Cache-Control": "no-store"})
