"""Disposable OAuth and MCP service shared by protocol and browser tests."""

import base64
import hashlib
import html
from contextlib import asynccontextmanager
from urllib.parse import urlencode
from aiohttp import web
from aiohttp.test_utils import TestServer


@asynccontextmanager
async def authorization_server():
    state = {
        "registrations": 0, "exchanges": 0, "refreshes": 0,
        "authorization": None, "cimd": False, "accepted_access": "fixture-access",
        "expires_in": 3600,
        "preregistered": False,
        "mcp": False, "calls": [], "tools": ["read_value", "write_value"],
        "auth_methods": ["none"], "reject_refresh": False,
    }

    async def protected(request):
        if request.headers.get("Authorization") == "Bearer " + state["accepted_access"]:
            return web.json_response({"connected": True})
        return web.Response(status=401, headers={
            "WWW-Authenticate": f'Bearer resource_metadata="{state["origin"]}/resource-metadata"',
        })

    async def resource_metadata(request):
        return web.json_response({
            "resource": state["endpoint"],
            "authorization_servers": [state["origin"]],
            "scopes_supported": ["tools"],
        })

    async def metadata(request):
        origin = state["origin"]
        body = {
            "issuer": origin,
            "authorization_endpoint": origin + "/authorize",
            "token_endpoint": origin + "/token",
            "registration_endpoint": origin + "/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": state["auth_methods"],
            "authorization_response_iss_parameter_supported": True,
            "client_id_metadata_document_supported": state["cimd"],
            "scopes_supported": ["tools"],
        }
        if state["preregistered"]:
            del body["registration_endpoint"]
        return web.json_response(body)

    async def register(request):
        body = await request.json()
        assert body["token_endpoint_auth_method"] == "none"
        if not state["mcp"]:
            assert body["redirect_uris"] == ["http://127.0.0.1:43210/callback"]
        state["registrations"] += 1
        return web.json_response({**body, "client_id": "fixture-client"}, status=201)

    async def token(request):
        body = await request.post()
        if body["grant_type"] == "refresh_token":
            assert body["refresh_token"] == "fixture-refresh"
            assert body["resource"] == state["endpoint"]
            state["refreshes"] += 1
            if state["reject_refresh"]:
                return web.json_response({"error": "invalid_grant"}, status=400)
            return web.json_response({
                "access_token": state["accepted_access"], "refresh_token": "rotated-refresh",
                "token_type": "Bearer", "expires_in": 3600, "scope": "tools",
            })
        state["exchanges"] += 1
        assert body["code"] == "fixture-code"
        assert body["grant_type"] == "authorization_code"
        assert body["resource"] == state["endpoint"]
        assert body["redirect_uri"] == state["authorization"]["redirect_uri"][0]
        assert body["client_id"] == state["authorization"]["client_id"][0]
        assert "client_secret" not in body
        digest = hashlib.sha256(body["code_verifier"].encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        assert challenge == state["authorization"]["code_challenge"][0]
        return web.json_response({
            "access_token": "fixture-access", "refresh_token": "fixture-refresh",
            "token_type": "Bearer", "expires_in": state["expires_in"], "scope": "tools",
        })

    app = web.Application()
    app.router.add_get("/mcp", protected)

    async def protocol(request):
        if request.headers.get("Authorization") != "Bearer " + state["accepted_access"]:
            return await protected(request)
        body = await request.json()
        if "id" not in body:
            return web.Response(status=202)
        envelope = {"jsonrpc": "2.0", "id": body["id"]}
        method = body["method"]
        if method == "server/discover":
            return web.json_response({**envelope, "error": {"code": -32601, "message": "Legacy fixture"}})
        if method == "initialize":
            result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "OAuth fixture", "version": "1"}}
        elif method == "tools/list":
            result = {"tools": [{"name": name, "description": name.replace("_", " "),
                                 "inputSchema": {"type": "object", "properties": {"value": {"type": "string"}}}}
                                for name in state["tools"]]}
        elif method == "tools/call":
            state["calls"].append(body["params"])
            result = {"content": [{"type": "text", "text": "fixture value"}], "isError": False}
        else:
            return web.json_response({**envelope, "error": {"code": -32601, "message": "Unknown method"}})
        return web.json_response({**envelope, "result": result})

    app.router.add_post("/mcp", protocol)

    async def authorize(request):
        if request.method == "GET":
            return web.Response(text='<h1>Local test service</h1><form method="post" action="'
                                + html.escape(str(request.rel_url), quote=True)
                                + '"><button>Allow test access</button></form>', content_type="text/html")
        state["authorization"] = {key: request.query.getall(key) for key in request.query}
        params = {"code": "fixture-code", "state": request.query["state"], "iss": state["origin"]}
        raise web.HTTPFound(request.query["redirect_uri"] + "?" + urlencode(params))

    app.router.add_route("*", "/authorize", authorize)
    app.router.add_get("/resource-metadata", resource_metadata)
    app.router.add_get("/.well-known/oauth-authorization-server", metadata)
    app.router.add_post("/register", register)
    app.router.add_post("/token", token)
    async with TestServer(app) as server:
        state["origin"] = str(server.make_url("/")).rstrip("/")
        state["endpoint"] = state["origin"] + "/mcp"
        yield state
