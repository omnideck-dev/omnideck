"""Real SDK transport behind omnideck's grant-enforcing dispatcher."""

import pytest
from mcp.server import MCPServer

from brokering._rpc import RpcError
from brokering.brokers.mcp_broker.client import MCPDispatcher, connect, discover
from tests.integration.brokering.mcp.test_sdk_transport import serve_sdk


async def test_discovery_grants_revocation_and_error_results():
    server = MCPServer("grant fixture")
    calls = []

    @server.tool()
    def set_value(value: str) -> str:
        """Set the fixture value."""
        calls.append(value)
        return value

    async with serve_sdk(server) as endpoint:
        async with connect(endpoint, allow_loopback=True) as client:
            operations = await discover(client)
            assert [operation.id for operation in operations] == ["mcp.set_value"]
            dispatcher = MCPDispatcher(client, operations)
            with pytest.raises(RpcError, match="not enabled"):
                await dispatcher.dispatch("mcp.set_value", {"value": "denied"})
            assert calls == []
            dispatcher.replace_operation_grants(frozenset({"mcp.set_value"}))
            result = await dispatcher.dispatch("mcp.set_value", {"value": "selected"})
            assert result["content"][0]["text"] == "selected"
            assert calls == ["selected"]
            dispatcher.replace_operation_grants(frozenset())
            with pytest.raises(RpcError, match="not enabled"):
                await dispatcher.dispatch("mcp.set_value", {"value": "revoked"})
            assert calls == ["selected"]


async def test_empty_catalog_connects_without_tools():
    async with serve_sdk(MCPServer("empty")) as endpoint:
        async with connect(endpoint, allow_loopback=True) as client:
            assert await discover(client) == ()
