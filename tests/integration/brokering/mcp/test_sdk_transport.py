"""Exercise the pinned SDK over real loopback HTTP, without external accounts.

The modern fixture is an official SDK server. The small legacy wire fixture
deliberately rejects discovery, proving automatic fallback rather than forcing
the client into legacy mode. These are compatibility gates, not app E2E tests.
"""

import asyncio
import socket
from contextlib import asynccontextmanager

import pytest
import uvicorn
from aiohttp import web
from aiohttp.test_utils import TestServer
from mcp import Client
from mcp.server import MCPServer


@asynccontextmanager
async def serve_sdk(server):
    # Retain the bound socket: finding a free port and closing it races other tests.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        app = server.streamable_http_app(json_response=True)
        runner = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
        task = asyncio.create_task(runner.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(10):
                while not runner.started:
                    if task.done():
                        await task
                        raise RuntimeError("MCP fixture stopped before startup")
                    await asyncio.sleep(0.01)
            yield f"http://127.0.0.1:{listener.getsockname()[1]}/mcp"
        finally:
            runner.should_exit = True
            try:
                await asyncio.wait_for(task, timeout=10)
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)


async def test_modern_discovery_and_call_over_http():
    server = MCPServer("omnideck compatibility fixture")

    @server.tool()
    def echo(value: str) -> str:
        """Return the supplied value."""
        return value

    async with serve_sdk(server) as endpoint:
        async with Client(endpoint) as client:
            assert client.protocol_version == "2026-07-28"
            catalog = await client.list_tools()
            assert [tool.name for tool in catalog.tools] == ["echo"]
            assert catalog.tools[0].input_schema["properties"]["value"]["type"] == "string"
            result = await client.call_tool("echo", {"value": "hello"})
            assert not result.is_error
            assert result.content[0].text == "hello"


async def test_empty_catalog_is_a_successful_connection():
    async with serve_sdk(MCPServer("empty fixture")) as endpoint:
        async with Client(endpoint) as client:
            assert (await client.list_tools()).tools == []


async def test_legacy_fallback_and_pagination_preserve_schema():
    seen = []
    schema = {
        "type": "object",
        "$defs": {"identifier": {"type": "string", "minLength": 1}},
        "properties": {"id": {"$ref": "#/$defs/identifier"}},
        "required": ["id"],
        "additionalProperties": False,
    }

    async def handle(request):
        if request.method != "POST":
            return web.Response(status=405)
        body = await request.json()
        method = body["method"]
        seen.append(method)
        if "id" not in body:
            return web.Response(status=202)
        envelope = {"jsonrpc": "2.0", "id": body["id"]}
        if method == "server/discover":
            return web.json_response({**envelope, "error": {"code": -32601, "message": "Unknown method"}})
        if method == "initialize":
            result = {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "legacy fixture", "version": "1"},
            }
        elif method == "tools/list":
            cursor = body.get("params", {}).get("cursor")
            assert cursor in (None, "page-2")
            result = {"tools": [{"name": "second" if cursor else "first", "inputSchema": schema}]}
            if not cursor:
                result["nextCursor"] = "page-2"
        elif method == "tools/call":
            assert body["params"]["name"] == "second"
            assert body["params"]["arguments"] == {"id": "123"}
            result = {"content": [{"type": "text", "text": "found"}], "isError": False}
        else:
            pytest.fail(f"Unexpected MCP method: {method}")
        return web.json_response({**envelope, "result": result})

    app = web.Application()
    app.router.add_route("*", "/mcp", handle)
    async with TestServer(app) as server:
        async with Client(str(server.make_url("/mcp"))) as client:
            assert client.protocol_version == "2025-11-25"
            first = await client.list_tools()
            second = await client.list_tools(cursor=first.next_cursor)
            assert first.next_cursor == "page-2"
            assert second.next_cursor is None
            assert first.tools[0].input_schema == second.tools[0].input_schema == schema
            assert (await client.call_tool("second", {"id": "123"})).content[0].text == "found"
    assert seen[:2] == ["server/discover", "initialize"]
