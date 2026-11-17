"""Agent schema validation precedes real supervisor/broker/remote execution."""

from types import SimpleNamespace
from pathlib import Path
import json

from mcp.server import MCPServer

from agent_core.tools import _execute_tool_call
from brokering.brokers.mcp_broker.catalog import MCP_DRIVER
from brokering.mcp_protocol import connect, discover
from brokering.supervisor._lifecycle import Supervisor
from brokering.supervisor._store import read_raw_meta
from integrations.catalog import IntegrationCatalogEntry
from integrations.connection_cache import IntegrationConnection
from integrations.discovery import parse_discovered_operations
from tools.integrations._mcp_tools import build_mcp_tool
from tools.integrations._tool_resolution import connection_tools
from tests.integration.brokering.mcp.fixtures import authorization_server
from tests.integration.brokering.mcp.test_sdk_transport import serve_sdk
from tests.integration.brokering.supervisor.test_supervisor import _rpc_call


async def test_invalid_agent_arguments_never_reach_remote_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("OMNIDECK_ENABLE_TEST_INTEGRATIONS", "1")
    calls = []
    remote = MCPServer("argument validation")

    @remote.tool()
    def record_count(count: int) -> str:
        """Record an integer without coercion."""
        calls.append(count)
        return f"recorded {count}"

    async with serve_sdk(remote) as endpoint:
        async with connect(endpoint) as client:
            operations = await discover(client)
        supervisor = Supervisor(
            vault_dir=tmp_path / "vault", app_sock_path=tmp_path / "app.sock",
            sockets_dir=tmp_path / "s", host_paths={},
            catalog={"mcp": IntegrationCatalogEntry("mcp", "MCP", "", "Custom", MCP_DRIVER)},
        )
        await supervisor.start()
        try:
            added = await _rpc_call(supervisor.app_sock_path, "add", {
                "kind": "integration", "slug": "mcp", "label": "Fixture", "user_suffix": "validation",
                "operation_grants": ["mcp.record_count"],
                "auth_blob": {"endpoint": endpoint, "access_token": "", "oauth_state": ""},
                "discovered_operations": [op.public_dict() for op in operations],
            })
            assert "error" not in added, added
            connection_id = added["result"]["id"]
            monkeypatch.setattr("integrations.service.load_config", lambda: SimpleNamespace(
                integrations=SimpleNamespace(app_sock_path=supervisor.app_sock_path),
            ))
            tool = build_mcp_tool(IntegrationConnection(connection_id, "mcp", label="Fixture"), operations[0])
            for arguments in ({}, {"count": "2"}, {"count": True}):
                result = await _execute_tool_call(tool.__name__, arguments, [tool])
                assert result.startswith("Argument validation failed:"), result
            assert calls == []
            result = await _execute_tool_call(tool.__name__, {"count": 2}, [tool])
            assert "recorded 2" in result
            assert calls == [2]
            # Schema validity does not replace broker authorization.
            revoked = await _rpc_call(supervisor.app_sock_path, "update", {
                "id": connection_id, "operation_grants": [],
            })
            assert "error" not in revoked, revoked
            result = await _execute_tool_call(tool.__name__, {"count": 3}, [tool])
            assert "not enabled" in result
            assert calls == [2]
        finally:
            await supervisor.stop()


async def test_rejected_schema_preserves_catalog_and_valid_tools_after_reconnect_and_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("OMNIDECK_ENABLE_TEST_INTEGRATIONS", "1")
    async with authorization_server() as state:
        state["mcp"] = True
        supervisor = Supervisor(
            vault_dir=tmp_path / "vault", app_sock_path=tmp_path / "app.sock",
            sockets_dir=tmp_path / "s", host_paths={},
            catalog={"mcp": IntegrationCatalogEntry("mcp", "MCP", "", "Custom", MCP_DRIVER)},
        )
        auth = {"endpoint": state["endpoint"], "access_token": state["accepted_access"], "oauth_state": ""}

        async def catalog():
            async with connect(state["endpoint"], token=state["accepted_access"]) as client:
                return [op.public_dict() for op in await discover(client)]

        async def rpc(verb, args):
            response = await _rpc_call(supervisor.app_sock_path, verb, args)
            assert "error" not in response, response
            return response["result"]

        await supervisor.start()
        try:
            record = await rpc("add", {
                "kind": "integration", "slug": "mcp", "label": "Mixed schemas", "user_suffix": "schemas",
                "operation_grants": ["mcp.read_value", "mcp.write_value"],
                "auth_blob": auth, "discovered_operations": await catalog(),
            })
            connection_id = record["id"]
            # A formerly approved tool becomes invalid during rediscovery.
            state["schemas"]["write_value"] = {"type": "object", "properties": {"value": {"type": "integerish"}}}
            raw_catalog = await catalog()
            await rpc("reconnect", {"id": connection_id, "auth_blob": auth, "discovered_operations": raw_catalog})
            for restart in (False, True):
                if restart:
                    await supervisor.stop()
                    await supervisor.start()
                record = (await rpc("list", {}))["connections"][0]
                assert record["state"] == "running"
                assert record["operation_grants"] == ["mcp.read_value", "mcp.write_value"]
                assert record["available_operation_ids"] == ["mcp.read_value"]
                assert record["operations"][1]["unavailable_reason"]
                assert read_raw_meta(supervisor.vault_dir, connection_id)["discovered_operations"] == raw_catalog
                connection = IntegrationConnection(
                    connection_id, "mcp", operation_grants=frozenset(record["operation_grants"]),
                    discovered_operations=parse_discovered_operations(json.dumps(record["operations"])),
                )
                assert len(connection_tools(connection)) == 1
                rejected = await _rpc_call(Path(record["socket"]), "mcp.write_value", {})
                assert rejected["error"]["code"] == "NOT_FOUND"
                accepted = await _rpc_call(Path(record["socket"]), "mcp.read_value", {})
                assert "error" not in accepted, accepted
            assert [call["name"] for call in state["calls"]] == ["read_value", "read_value"]
            await rpc("update", {"id": connection_id, "operation_grants": ["mcp.read_value", "mcp.write_value"]})
            record = (await rpc("list", {}))["connections"][0]
            assert record["operation_grants"] == ["mcp.read_value"]
        finally:
            await supervisor.stop()
