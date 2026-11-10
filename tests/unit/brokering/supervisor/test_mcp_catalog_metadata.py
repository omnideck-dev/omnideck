"""Catalog persistence and fail-closed recovery across the metadata/secret pair."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from brokering._rpc import RpcError
from brokering.brokers.mcp_broker.catalog import MCP_DRIVER
from brokering.connection_data import BrokerConnectionData
from brokering.supervisor._app_sock import AppSockHandler
from brokering.supervisor._manager import BrokerManager
from brokering.supervisor._operation_metadata import bind_mcp_catalog, connection_operations
from brokering.supervisor._registry import Registry
from brokering.supervisor._store import read_raw_meta, read_secrets, write_meta, write_secrets
from brokering.supervisor.types import IntegrationConnectionMeta, connection_meta_from_dict
from integrations.catalog import IntegrationCatalogEntry
from integrations.discovery import parse_discovered_operations


OPERATIONS = parse_discovered_operations(json.dumps([
    {"id": "mcp.search", "title": "Search", "description": "Search documents",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}}},
]))
ENTRY = IntegrationCatalogEntry("mcp", "MCP", "", "Custom", MCP_DRIVER)


def test_metadata_roundtrip_keeps_public_schema_and_rejects_invalid_catalog():
    now = datetime.now(UTC)
    meta = IntegrationConnectionMeta(
        id="mcp_work", slug="mcp", label="Work", added_at=now, updated_at=now,
        discovered_operations=OPERATIONS,
    )
    public = meta.model_dump(mode="json")
    assert public["discovered_operations"] == [operation.public_dict() for operation in OPERATIONS]
    assert connection_meta_from_dict(public) == meta
    public["discovered_operations"] *= 2
    with pytest.raises(ValueError):
        connection_meta_from_dict(public)


@pytest.mark.parametrize("verb", ["add", "reconnect"])
@pytest.mark.parametrize("payload", [
    {"auth_blob": {"discovered_operations": "[]"}},
    {"auth_blob": {}, "discovered_operations": [{"id": "invalid"}]},
])
async def test_invalid_or_legacy_catalog_never_reaches_manager(verb, payload):
    manager = SimpleNamespace(add=AsyncMock(), reconnect=AsyncMock())
    handler = AppSockHandler(manager=manager, registry=Registry())
    with pytest.raises(RpcError) as error:
        await handler.handle(verb, {"id": "mcp_work", "slug": "mcp", "label": "Work", **payload})
    assert error.value.code == "BAD_REQUEST"
    manager.add.assert_not_called()
    manager.reconnect.assert_not_called()


@pytest.mark.parametrize("stale_metadata", [False, True])
async def test_mixed_catalog_credentials_stay_broken_until_reconnect(tmp_path, monkeypatch, stale_metadata):
    now = datetime.now(UTC)
    meta = IntegrationConnectionMeta(
        id="mcp_work", slug="mcp", label="Work", added_at=now, updated_at=now,
        agent_operation_grants=frozenset({"mcp.search"}),
        discovered_operations=() if stale_metadata else OPERATIONS,
    )
    fields = BrokerConnectionData({"endpoint": "https://example.com/mcp", "access_token": "private"})
    key = b"x" * 32
    write_meta(tmp_path, meta)
    write_secrets(tmp_path, meta.id, key, bind_mcp_catalog(fields, OPERATIONS if stale_metadata else ()))
    spawn = AsyncMock()
    monkeypatch.setattr("brokering.supervisor._manager.spawn_broker", spawn)
    manager = BrokerManager(
        vault_dir=tmp_path, sockets_dir=tmp_path / "sockets", master_key=key, host_paths={},
        registry=Registry(), catalog={"mcp": ENTRY},
    )
    record = await manager.reconcile_existing(meta.id)
    assert record.state == "broken" and record.broker is None
    assert record.meta.agent_operation_grants == meta.agent_operation_grants
    spawn.assert_not_called()
    manager._start_watcher = Mock()
    await manager.reconnect(meta.id, auth_blob=fields, discovered_operations=OPERATIONS)
    assert record.state == "running"
    assert record.discovered_operations == OPERATIONS
    assert record.meta.agent_operation_grants == meta.agent_operation_grants
    saved = read_secrets(tmp_path, meta.id, key)
    assert "discovered_operations" not in saved
    assert read_raw_meta(tmp_path, meta.id)["discovered_operations"] == [op.public_dict() for op in OPERATIONS]
    assert connection_operations(ENTRY, saved, OPERATIONS) == frozenset({"mcp.search"})
