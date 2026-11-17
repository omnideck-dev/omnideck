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
    manager._refresh_authorization_fields = AsyncMock(return_value=new)
    manager._update_credentials = AsyncMock(side_effect=RuntimeError("activation failed"))
    manager._stop_record_broker = AsyncMock()
    with pytest.raises(RpcError, match="refresh access"):
        await BrokerManager.ensure_fresh_authorization.__wrapped__(manager, "mcp_one")
    args = manager._update_credentials.await_args.args
    assert args[2] is new and args[3] is new
    assert record.state == "broken"
    manager._stop_record_broker.assert_awaited_once_with(record)


@pytest.mark.parametrize('driver', ['remote.mcp', 'native.google_workspace'])
async def test_concurrent_rejections_refresh_once_per_generation(monkeypatch, driver):
    import asyncio
    from brokering.supervisor._registry import BrokeredConnectionRecord, Registry
    from brokering.supervisor.types import IntegrationConnectionMeta
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    meta = IntegrationConnectionMeta(id='test', slug='test', label='test', added_at=now, updated_at=now)
    record = BrokeredConnectionRecord(meta=meta, broker=None, driver_id=driver)
    old_generation = record.authorization_generation
    manager = object.__new__(BrokerManager)
    manager._registry = Registry()
    manager._registry.add(record)
    manager._catalog = {'test': SimpleNamespace(driver_id=driver)}
    manager._vault_dir = None
    manager._master_key = b'fixture'
    old = BrokerConnectionData({'access_token': 'old'})
    new = BrokerConnectionData({'access_token': 'new'})
    monkeypatch.setattr('brokering.supervisor._manager.read_secrets', lambda *args: old)
    manager._refresh_authorization_fields = AsyncMock(return_value=new)
    async def activate(*args):
        await asyncio.sleep(0)
        record.authorization_generation = 'new-generation'
    manager._update_credentials = AsyncMock(side_effect=activate)
    results = await asyncio.gather(*(manager.renew_rejected_authorization('test', old_generation) for _ in range(8)))
    assert results.count(True) == 1
    manager._refresh_authorization_fields.assert_awaited_once_with(manager._catalog['test'], 'test', old, force=True)
    assert manager._update_credentials.await_args.args[2:4] == (new, new)


@pytest.mark.parametrize('driver', ['remote.mcp', 'native.google_workspace'])
async def test_cancelled_refresh_finishes_persistence_before_releasing_owner(monkeypatch, driver):
    import asyncio
    started, finish = asyncio.Event(), asyncio.Event()
    saved = []
    async def refresh(fields, persist, *, force):
        started.set()
        await finish.wait()
        updated = BrokerConnectionData({'access_token': 'new'})
        persist(updated)
        return updated
    module = 'refresh_mcp_authorization' if driver == 'remote.mcp' else 'refresh_google_authorization'
    monkeypatch.setattr(f'brokering.supervisor._manager.{module}', refresh)
    monkeypatch.setattr('brokering.supervisor._manager.write_secrets', lambda *args: saved.append(args[-1]))
    manager = object.__new__(BrokerManager)
    manager._vault_dir = None
    manager._master_key = b'fixture'
    task = asyncio.create_task(manager._refresh_authorization_fields(SimpleNamespace(driver_id=driver), 'test', BrokerConnectionData({}), force=True))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert saved[0]['access_token'] == 'new'
