"""Exercise broker reconnects and single-dispatch semantics across MCP transport loss."""

import asyncio
from contextlib import asynccontextmanager

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from mcp import Client
from mcp.server import MCPServer

from brokering._rpc import RpcError
from brokering.brokers.mcp_broker._session import create_session
from brokering.mcp_protocol import discover
from tests.integration.brokering.mcp.test_sdk_transport import serve_sdk


async def test_failed_idle_transport_reconnects_before_next_invocation(monkeypatch):
    server = MCPServer("idle disconnect fixture")
    calls = []
    starts = []
    fail, closed = asyncio.Event(), asyncio.Event()

    @server.tool()
    def write(value: str) -> str:
        calls.append(value)
        return value

    @asynccontextmanager
    async def interrupt_first_client(*args, **kwargs):
        starts.append(True)
        try:
            async with Client(*args, **kwargs) as client:
                if len(starts) > 1:
                    yield client
                    return
                async with asyncio.TaskGroup() as tasks:
                    async def interrupt():
                        await fail.wait()
                        raise ConnectionResetError("fixture transport ended")
                    tasks.create_task(interrupt())
                    yield client
        finally:
            closed.set()

    monkeypatch.setattr("brokering.mcp_protocol._client.Client", interrupt_first_client)
    async with serve_sdk(server) as endpoint:
        fields = {"MCP_ENDPOINT": endpoint, "MCP_ACCESS_TOKEN": ""}
        async with create_session(fields) as broker:
            fields.clear()
            broker.replace_operation_grants(frozenset({"mcp.write"}))
            await broker.dispatch("mcp.write", {"value": "before"})
            fail.set()
            await asyncio.wait_for(closed.wait(), 3)
            result = await broker.dispatch("mcp.write", {"value": "after"})
            assert result["content"][0]["text"] == "after"
    assert calls == ["before", "after"] and len(starts) == 2


async def test_unconfirmed_result_reconnects_once_preserving_grants_and_inflight_calls():
    handshakes = []
    calls = []
    hold, release = asyncio.Event(), asyncio.Event()
    rediscover, publish = asyncio.Event(), asyncio.Event()

    async def handle(request):
        assert request.headers["Authorization"] == "Bearer session-test"
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
            handshakes.append(True)
            response["result"] = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
                                  "serverInfo": {"name": "session fixture", "version": "1"}}
        elif method == "tools/list":
            available = ["write", "hold", "read", "revoked", "removed"]
            if len(handshakes) == 2:
                rediscover.set()
                await publish.wait()
                available.remove("removed")
            response["result"] = {"tools": [{"name": name, "inputSchema": {"type": "object"}} for name in available]}
        else:
            assert method == "tools/call"
            name = packet["params"]["name"]
            calls.append(name)
            if name == "write":
                return web.Response(status=500)
            if name == "hold":
                hold.set()
                await release.wait()
            response["result"] = {"content": [{"type": "text", "text": name}]}
        return web.json_response(response)

    app = web.Application()
    app.router.add_route("*", "/mcp", handle)
    async with TestServer(app) as server:
        fields = {"MCP_ENDPOINT": str(server.make_url("/mcp")), "MCP_ACCESS_TOKEN": "session-test"}
        async with create_session(fields) as broker, asyncio.timeout(12):
            grants = frozenset({"mcp.write", "mcp.hold", "mcp.read", "mcp.revoked", "mcp.removed"})
            broker.replace_operation_grants(grants)
            pending = asyncio.create_task(broker.dispatch("mcp.hold", {}))
            try:
                await hold.wait()
                with pytest.raises(RpcError, match="may have completed"):
                    await broker.dispatch("mcp.write", {})
                with pytest.raises(RpcError, match="not enabled"):
                    await broker.dispatch("mcp.ungranted", {})
                assert calls == ["hold", "write"] and len(handshakes) == 1
                revoked = asyncio.create_task(broker.dispatch("mcp.revoked", {}))
                await rediscover.wait()
                reads = asyncio.gather(broker.dispatch("mcp.read", {}), broker.dispatch("mcp.read", {}))
                broker.replace_operation_grants(grants - {"mcp.revoked"})
                publish.set()
                with pytest.raises(RpcError, match="not enabled"):
                    await revoked
                assert [r["content"][0]["text"] for r in await reads] == ["read", "read"]
                with pytest.raises(RpcError, match="no longer available"):
                    await broker.dispatch("mcp.removed", {})
                assert not pending.done()
            finally:
                publish.set()
                release.set()
                assert (await pending)["content"][0]["text"] == "hold"
    assert len(handshakes) == 2 and calls == ["hold", "write", "read", "read"]


async def test_tool_timeout_keeps_unknown_result_and_the_session(monkeypatch):
    server = MCPServer("deadline fixture")
    entered, release = asyncio.Event(), asyncio.Event()
    calls, discoveries = [], []

    @server.tool()
    async def render() -> str:
        calls.append("render")
        entered.set()
        await release.wait()
        return "done"

    @server.tool()
    def status() -> str:
        calls.append("status")
        return "ready"

    async def discovery(client):
        discoveries.append(True)
        return await discover(client)

    monkeypatch.setattr("brokering.brokers.mcp_broker._session.discover", discovery)
    monkeypatch.setattr("brokering.brokers.mcp_broker.client.TOOL_CALL_SECONDS", 0.2)
    async with serve_sdk(server) as endpoint:
        async with create_session({"MCP_ENDPOINT": endpoint, "MCP_ACCESS_TOKEN": ""}) as broker:
            broker.replace_operation_grants(frozenset({"mcp.render", "mcp.status"}))
            try:
                with pytest.raises(RpcError) as error:
                    await broker.dispatch("mcp.render", {})
                assert error.value.code == "MCP_TOOL_TIMEOUT" and entered.is_set()
                assert "may have completed" in error.value.message
                result = await broker.dispatch("mcp.status", {})
                assert result["content"][0]["text"] == "ready"
            finally:
                release.set()
    assert calls == ["render", "status"] and len(discoveries) == 1


async def test_failed_reconnect_sends_no_tool_and_a_later_reconnect_succeeds(monkeypatch):
    server = MCPServer("reconnect failure fixture")
    calls, discoveries, starts = [], [], []
    fail, closed = asyncio.Event(), asyncio.Event()

    @server.tool()
    def status() -> str:
        calls.append("status")
        return "ready"

    @asynccontextmanager
    async def interrupt_first_client(*args, **kwargs):
        starts.append(True)
        try:
            async with Client(*args, **kwargs) as client:
                if len(starts) > 1:
                    yield client
                    return
                async with asyncio.TaskGroup() as tasks:
                    async def interrupt():
                        await fail.wait()
                        raise ConnectionResetError("fixture transport ended")
                    tasks.create_task(interrupt())
                    yield client
        finally:
            if len(starts) == 1:
                closed.set()

    async def discovery(client):
        discoveries.append(True)
        if len(discoveries) == 2:
            raise ConnectionResetError("fixture failure during discovery")
        return await discover(client)

    monkeypatch.setattr("brokering.mcp_protocol._client.Client", interrupt_first_client)
    monkeypatch.setattr("brokering.brokers.mcp_broker._session.discover", discovery)
    async with serve_sdk(server) as endpoint:
        async with create_session({"MCP_ENDPOINT": endpoint, "MCP_ACCESS_TOKEN": ""}) as broker:
            broker.replace_operation_grants(frozenset({"mcp.status"}))
            fail.set()
            await asyncio.wait_for(closed.wait(), 3)
            with pytest.raises(RpcError, match="not invoked") as error:
                await broker.dispatch("mcp.status", {})
            assert error.value.code == "UNAVAILABLE" and calls == []
            result = await broker.dispatch("mcp.status", {})
            assert result["content"][0]["text"] == "ready"
    assert calls == ["status"] and len(discoveries) == 3
