"""Local limits remain actionable through SDK HTTP and public setup status."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.server import MCPServer

from brokering._rpc import RpcError
from brokering.mcp_protocol import MCPFailure, MCPRequestError, mcp_error_boundary
from brokering.brokers.mcp_broker.client import MCPDispatcher
from brokering.mcp_protocol import connect, discover
from integrations.discovery import DiscoveredOperation
from server.oauth_setup.coordinator import OAuthSetupCoordinator
from server.oauth_setup.adapters.mcp import MCPOAuthAdapter
from server.oauth_setup.models import NewConnection, PreparedConnection
from tests.integration.brokering.mcp.test_sdk_transport import serve_sdk


@pytest.mark.parametrize("size,code", [
    # SDK includes both text and structured content, so 1.5 MiB of source
    # data crosses the 2 MiB result cap but stays below the 4 MiB wire cap.
    (1536 * 1024, "MCP_RESULT_SIZE_LIMIT"),
    (4 * 1024 * 1024, "MCP_RESPONSE_SIZE_LIMIT"),
])
async def test_large_tool_results_explain_limit_without_replaying(size, code):
    server = MCPServer("large result fixture")
    calls = []

    @server.tool()
    def large_result() -> str:
        """Return a deliberately oversized result."""
        calls.append(True)
        return "x" * size

    async with serve_sdk(server) as endpoint:
        async with connect(endpoint) as client:
            dispatcher = MCPDispatcher(client, await discover(client))
            dispatcher.replace_operation_grants(frozenset({"mcp.large_result"}))
            with pytest.raises(RpcError) as caught:
                await dispatcher.dispatch("mcp.large_result", {})
            assert caught.value.code == code
            assert "MiB limit" in caught.value.message
            assert "may have completed" in caught.value.message
            assert "Check the service before retrying" in caught.value.message
    assert calls == [True]


@pytest.mark.parametrize("kind,code,detail", [
    ("count", "MCP_TOOL_COUNT_LIMIT", "500 tools"),
    ("catalog", "MCP_CATALOG_SIZE_LIMIT", "1 MiB limit"),
    ("timeout", "MCP_DISCOVERY_TIMEOUT", "30-second limit"),
])
async def test_discovery_failure_reaches_setup_without_committing(monkeypatch, kind, code, detail):
    commit = AsyncMock()
    manager = OAuthSetupCoordinator(commit=commit, refresh=AsyncMock())
    tool = SimpleNamespace(name="read", title=None, description="", input_schema={"type": "object"})
    if kind == "catalog":
        tool.input_schema["description"] = "x" * (1024 * 1024)
    page = SimpleNamespace(tools=[tool] * (501 if kind == "count" else 1), next_cursor=None)
    client = SimpleNamespace(list_tools=AsyncMock(return_value=page))
    if kind == "timeout":
        client.list_tools.side_effect = TimeoutError("secret upstream response")

    async def authorize(self, browser):
        return PreparedConnection({}, await discover(client))

    monkeypatch.setattr(MCPOAuthAdapter, "_authorize_and_discover", authorize)
    try:
        pending = await manager.start(MCPOAuthAdapter({"endpoint": "https://fixture.test"}), NewConnection("mcp", "Fixture", "fixture", ()), redirect_uri="http://localhost:9000/callback")
        await pending.task
        status = pending.public_status()
        assert status["status"] == "error"
        assert status["error"]["code"] == code
        assert detail in status["error"]["message"]
        assert "secret" not in str(status)
        commit.assert_not_awaited()
    finally:
        await manager.close()


async def test_catalog_limit_survives_real_sdk_setup_teardown():
    server = MCPServer("too many tools fixture")

    def read() -> str:
        """Read a fixture value."""
        return "ok"

    for index in range(501):
        server.tool(name=f"read_{index}")(read)
    commit = AsyncMock()
    async with serve_sdk(server) as endpoint:
        manager = OAuthSetupCoordinator(commit=commit, refresh=AsyncMock())
        try:
            pending = await manager.start(MCPOAuthAdapter({"endpoint": endpoint}), NewConnection("mcp", "Fixture", "fixture", ()), redirect_uri="http://localhost:9000/callback")
            await pending.task
            assert pending.public_status()["error"]["code"] == "MCP_TOOL_COUNT_LIMIT"
            assert "500 tools" in pending.public_status()["error"]["message"]
            commit.assert_not_awaited()
        finally:
            await manager.close()


async def test_tool_deadline_explains_unknown_outcome_without_replay(monkeypatch):
    # Exercise the actual timeout path without waiting a minute in the suite.
    timeout = asyncio.timeout
    monkeypatch.setattr("brokering.brokers.mcp_broker.client.asyncio.timeout", lambda seconds: timeout(0.01))

    async def wait(*args):
        await asyncio.Event().wait()

    send = AsyncMock(side_effect=wait)
    operation = DiscoveredOperation("mcp.slow", "Slow", "", '{"type": "object"}')
    dispatcher = MCPDispatcher(SimpleNamespace(session=SimpleNamespace(send_request=send)), (operation,))
    dispatcher.replace_operation_grants(frozenset({"mcp.slow"}))
    with pytest.raises(RpcError) as caught:
        await dispatcher.dispatch("mcp.slow", {})
    assert caught.value.code == "MCP_TOOL_TIMEOUT"
    assert "60-second limit" in caught.value.message
    assert "may have completed" in caught.value.message
    assert send.await_count == 1


async def test_unknown_setup_errors_remain_sanitized(monkeypatch):
    manager = OAuthSetupCoordinator(commit=AsyncMock(), refresh=AsyncMock())
    monkeypatch.setattr(MCPOAuthAdapter, "_authorize_and_discover", AsyncMock(side_effect=ValueError("secret token")))
    try:
        pending = await manager.start(MCPOAuthAdapter({"endpoint": "https://fixture.test"}), NewConnection("mcp", "Fixture", "fixture", ()), redirect_uri="http://localhost:9000/callback")
        await pending.task
        assert pending.public_status()["error"]["code"] == "AUTH"
        assert "secret" not in str(pending.public_status())
    finally:
        await manager.close()


async def test_transport_error_state_is_scoped_to_each_request():
    from brokering.mcp_protocol import request_failure

    ready = asyncio.Event()

    async def failed():
        with pytest.raises(MCPRequestError, match="4 MiB"):
            with mcp_error_boundary():
                # Model the SDK swallowing a typed error in a child task.
                async def transport():
                    request_failure(MCPFailure.RESPONSE_SIZE)
                    ready.set()
                await asyncio.create_task(transport())
                raise RuntimeError("SDK connection closed")

    async def successful():
        with mcp_error_boundary():
            await ready.wait()

    await asyncio.gather(failed(), successful())
