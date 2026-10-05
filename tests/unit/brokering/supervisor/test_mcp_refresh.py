"""A failed activation must not roll rotating refresh tokens back on disk."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from brokering._rpc import RpcError
from brokering.connection_data import BrokerConnectionData
from brokering.supervisor._manager import BrokerManager


async def test_new_credentials_remain_authoritative_if_activation_fails(monkeypatch):
    old = BrokerConnectionData({"access_token": "old"})
    new = BrokerConnectionData({"access_token": "rotated"})
    record = SimpleNamespace(meta=SimpleNamespace(slug="mcp"), state="running", available_operations=frozenset())
    manager = object.__new__(BrokerManager)
    manager._registry = SimpleNamespace(get=lambda _: record)
    manager._catalog = {"mcp": SimpleNamespace(driver_id="remote.mcp")}
    manager._vault_dir = None
    manager._master_key = b"fixture"
    monkeypatch.setattr("brokering.supervisor._manager.read_secrets", lambda *args: old)
    manager._refresh_mcp_fields = AsyncMock(return_value=new)
    manager._update_credentials = AsyncMock(side_effect=RuntimeError("activation failed"))
    manager._stop_record_broker = AsyncMock()
    with pytest.raises(RpcError, match="refresh access"):
        await BrokerManager.ensure_fresh_authorization.__wrapped__(manager, "mcp_one")
    args = manager._update_credentials.await_args.args
    assert args[2] is new and args[3] is new
    assert record.state == "broken"
    manager._stop_record_broker.assert_awaited_once_with(record)
