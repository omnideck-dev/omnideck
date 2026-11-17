"""HTTP translation and application lifetime for the shared OAuth coordinator."""

import html
import os
import secrets

from aiohttp import web

from server._brokering import supervisor_call
from server._integration_cache import INTEGRATION_CACHE_KEY
from server._integrations_http import error_response
from .adapters.mcp import MCP_CALLBACK_PATH, callback_uri
from .callback import CallbackReply, OAuthCallback
from .coordinator import OAuthSetupCoordinator

SETUP_KEY = web.AppKey("oauth_setup", OAuthSetupCoordinator)
MCP_REDIRECT_KEY = web.AppKey("mcp_redirect_uri", str)
GOOGLE_CALLBACK_PATH = "/api/integrations/oauth/callback"


def callback_response(reply: CallbackReply) -> web.Response:
    # Only a nonce-authorized close script runs; provider input is never rendered.
    nonce = secrets.token_urlsafe(24)
    return web.Response(status=reply.status, content_type="text/html", text=(
        "<!doctype html><html><head><meta charset='utf-8'><title>omnideck sign-in</title></head><body>"
        f"<p>{html.escape(reply.message)}</p>"
        f'<script nonce="{nonce}">setTimeout(()=>window.close(),1500)</script>'
        "</body></html>"
    ), headers={
        "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": f"default-src 'none'; script-src 'nonce-{nonce}'; frame-ancestors 'none'",
        "X-Content-Type-Options": "nosniff",
    })


def receive_callback(receiver: OAuthCallback, request: web.Request) -> web.Response:
    return callback_response(receiver.accept(
        authority=request.headers.get("Host", ""), query_string=request.rel_url.raw_query_string,
    ))


async def callback(request: web.Request) -> web.Response:
    receiver = request.app[SETUP_KEY].callback(request.query.get("state", ""), request.path)
    if receiver is None:
        return callback_response(CallbackReply(410, "This sign-in attempt is no longer available. Return to omnideck."))
    return receive_callback(receiver, request)


async def status(request: web.Request) -> web.Response:
    pending = request.app[SETUP_KEY].status(request.match_info["state"])
    if pending is None:
        return error_response("NOT_FOUND", "Sign-in attempt expired. Start again.")
    return web.json_response(pending.public_status(), headers={"Cache-Control": "no-store"})


async def cancel(request: web.Request) -> web.Response:
    pending = await request.app[SETUP_KEY].cancel(request.match_info["state"])
    result = pending.public_status() if pending is not None else {"status": "cancelled"}
    if pending is not None and pending.status == "committing":
        return web.json_response({"error": {"code": "BUSY", "message": "The connection is being saved. Wait for it to finish before closing setup."}}, status=409)
    return web.json_response(result, headers={"Cache-Control": "no-store"})


def register_oauth_routes(app: web.Application) -> None:
    from .google_routes import start as start_google
    from .mcp_routes import connection_settings, start as start_mcp

    async def refresh() -> bool:
        return await app[INTEGRATION_CACHE_KEY].refresh()

    app[SETUP_KEY] = OAuthSetupCoordinator(commit=supervisor_call, refresh=refresh)
    app.router.add_post("/api/integrations/oauth/start", start_google)
    app.router.add_get(GOOGLE_CALLBACK_PATH, callback, allow_head=False)
    # Preserve existing API URLs and registered callback addresses. Both route
    # families use the same coordinator and the same status/cancel handlers.
    prefixes = ["/api/integrations/oauth"]
    if origin := os.environ.get("OMNIDECK_EXTERNAL_URL"):
        app[MCP_REDIRECT_KEY] = callback_uri(origin)
        app.router.add_get("/api/integrations/mcp/connection-settings", connection_settings)
        app.router.add_post("/api/integrations/mcp/oauth/start", start_mcp)
        app.router.add_get(MCP_CALLBACK_PATH, callback, allow_head=False)
        prefixes.append("/api/integrations/mcp/oauth")
    for prefix in prefixes:
        app.router.add_get(f"{prefix}/status/{{state}}", status)
        app.router.add_delete(f"{prefix}/status/{{state}}", cancel)

    async def cleanup(_app: web.Application) -> None:
        await app[SETUP_KEY].close()

    app.on_cleanup.append(cleanup)
