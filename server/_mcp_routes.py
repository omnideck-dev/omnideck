"""MCP setup routes; provider tokens never cross the browser boundary."""

import json
import os
import re

from aiohttp import web

from integrations.catalog import integration_catalog, test_integrations_enabled
from integrations.catalog.slack import SLACK_MCP_ENDPOINT, SLACK_MCP_ISSUER, SLACK_MCP_SCOPES, slack_app_manifest
from server._brokering import supervisor_call
from server._integration_cache import INTEGRATION_CACHE_KEY
from server._integrations_http import error_response
from server._mcp_oauth_callback import CALLBACK_PATH, MCPOAuthCallback
from server._mcp_setup import MCPSetupManager

MCP_SETUP_KEY = web.AppKey("mcp_setup", MCPSetupManager)


async def connection_settings(request: web.Request) -> web.Response:
    redirect_uri = request.app[MCP_SETUP_KEY].redirect_uri
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
        pending = await request.app[MCP_SETUP_KEY].start(body)
    except (ValueError, json.JSONDecodeError):
        return error_response("BAD_REQUEST", "Check the connection settings and try again.")
    except Exception:
        return error_response("UPSTREAM", "Could not start sign-in. Check the server and retry.")
    return web.json_response({**pending.public_status(), "authorize_url": pending.authorize_url}, headers={"Cache-Control": "no-store"})


async def callback(request: web.Request) -> web.Response:
    receiver = request.app[MCP_SETUP_KEY].callback(request.query.get("state", ""))
    if receiver is None:
        return MCPOAuthCallback._response(410, "This sign-in attempt is no longer available. Return to omnideck.")
    return await receiver.handle_callback(request)


async def status(request: web.Request) -> web.Response:
    pending = request.app[MCP_SETUP_KEY].status(request.match_info["state"])
    if pending is None:
        return error_response("NOT_FOUND", "Sign-in attempt expired. Start again.")
    return web.json_response(pending.public_status(), headers={"Cache-Control": "no-store"})


async def cancel(request: web.Request) -> web.Response:
    pending = await request.app[MCP_SETUP_KEY].cancel(request.match_info["state"])
    if pending is None:
        return error_response("NOT_FOUND", "Sign-in attempt expired.")
    return web.json_response(pending.public_status(), headers={"Cache-Control": "no-store"})


def register_mcp_routes(app: web.Application) -> None:
    origin = os.environ.get("OMNIDECK_EXTERNAL_URL")
    if not origin:
        return
    async def commit(verb: str, args: dict) -> dict:
        result = await supervisor_call(verb, args)
        await app[INTEGRATION_CACHE_KEY].refresh()
        return result

    manager = MCPSetupManager(callback_origin=origin, commit=commit, allow_loopback=test_integrations_enabled())
    app[MCP_SETUP_KEY] = manager
    app.router.add_get("/api/integrations/mcp/connection-settings", connection_settings)
    app.router.add_post("/api/integrations/mcp/oauth/start", start)
    app.router.add_get(CALLBACK_PATH, callback, allow_head=False)
    app.router.add_get("/api/integrations/mcp/oauth/status/{state}", status)
    app.router.add_delete("/api/integrations/mcp/oauth/status/{state}", cancel)

    async def cleanup(_app: web.Application) -> None:
        await manager.close()

    app.on_cleanup.append(cleanup)
