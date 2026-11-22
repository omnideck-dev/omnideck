"""Prove one failed MCP request fails only its own tool call, not the broker's session."""

import asyncio
from contextlib import asynccontextmanager

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from brokering._rpc import RpcError
from brokering.brokers.mcp_broker._session import create_session

GRANTS = frozenset({"mcp.hold", "mcp.drop", "mcp.stall", "mcp.quick"})


@asynccontextmanager
async def wire_server():
    state = {"handshakes": 0, "calls": [], "hold": asyncio.Event(), "release": asyncio.Event()}

    async def handle(request):
        if request.method != "POST":
            return web.Response(status=405)
        packet = await request.json()
        if "id" not in packet:
            return web.Response(status=202)
        response = {"jsonrpc": "2.0", "id": packet["id"]}
        method = packet["method"]
        if method == "server/discover":
            response["error"] = {"code": -32601, "message": "Unknown method"}
        elif method == "initialize":
            state["handshakes"] += 1
            response["result"] = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
                                  "serverInfo": {"name": "isolation fixture", "version": "1"}}
        elif method == "tools/list":
            tools = ["hold", "drop", "stall", "quick"]
            response["result"] = {"tools": [{"name": name, "inputSchema": {"type": "object"}} for name in tools]}
        else:
            name = packet["params"]["name"]
            state["calls"].append(name)
            if name == "drop":
                request.transport.abort()
                return web.Response(status=500)
            if name == "stall":
                await asyncio.Event().wait()
            if name == "hold":
                state["hold"].set()
                await state["release"].wait()
            response["result"] = {"content": [{"type": "text", "text": name}]}
        return web.json_response(response)

    app = web.Application()
    app.router.add_route("*", "/mcp", handle)
    async with TestServer(app) as server:
        fields = {"MCP_ENDPOINT": str(server.make_url("/mcp")), "MCP_ACCESS_TOKEN": ""}
        async with create_session(fields) as broker, asyncio.timeout(10):
            broker.replace_operation_grants(GRANTS)
            yield broker, state


async def test_dropped_request_leaves_other_calls_and_the_session_working():
    async with wire_server() as (broker, state):
        pending = asyncio.create_task(broker.dispatch("mcp.hold", {}))
        await state["hold"].wait()
        with pytest.raises(RpcError, match="may have completed") as error:
            await broker.dispatch("mcp.drop", {})
        assert error.value.code == "MCP_NETWORK_ERROR"
        assert (await broker.dispatch("mcp.quick", {}))["content"][0]["text"] == "quick"
        state["release"].set()
        assert (await pending)["content"][0]["text"] == "hold"
    assert state["handshakes"] == 1
    assert state["calls"] == ["hold", "drop", "quick"]


async def test_stalled_request_times_out_alone_and_the_session_keeps_working(monkeypatch):
    monkeypatch.setattr("brokering.mcp_protocol._network.TOOL_READ_SECONDS", 0.3)
    async with wire_server() as (broker, state):
        with pytest.raises(RpcError, match="may have completed") as error:
            await broker.dispatch("mcp.stall", {})
        assert error.value.code == "MCP_NETWORK_TIMEOUT"
        assert (await broker.dispatch("mcp.quick", {}))["content"][0]["text"] == "quick"
    assert state["handshakes"] == 1
    assert state["calls"] == ["stall", "quick"]
