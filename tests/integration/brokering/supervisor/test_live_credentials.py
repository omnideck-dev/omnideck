"""Real child credential handoffs: no restart, rejection, durability, and failure."""

import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from brokering._rpc import RpcError
from brokering.connection_data import BrokerConnectionData
from brokering.supervisor import _manager
from brokering.supervisor._lifecycle import Supervisor
from brokering.supervisor._store import read_secrets
from integrations.catalog import build_integration_catalog
from tests.integration.brokering.supervisor.test_live_grants import running, GET, SET, CREDS
from tests.integration.brokering.supervisor.test_supervisor import _rpc_call
from tests.integration.integrations.fixtures._host_paths import make_host_paths


def saved(sup, record):
    return read_secrets(sup.vault_dir, record.meta.id, sup._manager._master_key)


async def test_live_credentials_keep_process_state_grants_and_persist(running):
    sup, record = running
    proc = record.broker.proc
    await _rpc_call(record.broker.socket_path, SET, {"value": "retained"})
    await sup._manager.update(record.meta.id, operation_grants=frozenset({GET}))
    replacement = BrokerConnectionData({**dict(CREDS), "marker": "new"})
    await sup._manager.reconnect(record.meta.id, auth_blob=replacement)
    assert record.broker.proc is proc
    assert record.state == "running"
    assert (await _rpc_call(record.broker.socket_path, GET, {}))["result"]["value"] == "retained"
    assert (await _rpc_call(record.broker.socket_path, SET, {"value": "no"}))["error"]["code"] == "PERMISSION_DENIED"
    assert dict(saved(sup, record)) == dict(replacement)
    await sup.stop()
    await sup.start()
    assert sup._registry.get(record.meta.id).state == "running"
    assert dict(saved(sup, record)) == dict(replacement)


async def test_rejected_credentials_leave_process_and_vault_unchanged(running):
    sup, record = running
    proc = record.broker.proc
    before = saved(sup, record)
    with pytest.raises(RpcError) as rejected:
        await sup._manager.reconnect(record.meta.id, auth_blob=BrokerConnectionData({"token": "wrong-secret"}))
    assert rejected.value.code == "AUTH"
    assert "wrong-secret" not in str(rejected.value)
    assert record.broker.proc is proc
    assert record.state == "running"
    assert saved(sup, record) == before
    assert "result" in await _rpc_call(record.broker.socket_path, GET, {})
    # A rejected prepare must not leave a pending candidate blocking future changes.
    await sup._manager.reconnect(record.meta.id, auth_blob=CREDS)
    await sup._manager.update(record.meta.id, operation_grants=frozenset({GET}))


async def test_persist_failure_discards_candidate_and_keeps_old_connection(running, monkeypatch):
    sup, record = running
    proc = record.broker.proc
    original = _manager.write_meta
    calls = 0

    def fail_once(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("disk full")
        return original(*args)

    monkeypatch.setattr(_manager, "write_meta", fail_once)
    with pytest.raises(RpcError, match="could not save"):
        await sup._manager.reconnect(record.meta.id, auth_blob=BrokerConnectionData({**dict(CREDS), "marker": "new"}))
    assert record.broker.proc is proc
    assert saved(sup, record) == CREDS
    assert "result" in await _rpc_call(record.broker.socket_path, GET, {})
    await sup._manager.reconnect(record.meta.id, auth_blob=CREDS)


@pytest.mark.parametrize("phase", ["prepare_credentials", "activate_credentials"])
@pytest.mark.parametrize("failure", ["lost_ack", "cancel"])
async def test_ambiguous_handoff_stops_child_and_recovers_from_disk(running, monkeypatch, phase, failure):
    sup, record = running
    proc = record.broker.proc
    real_command = _manager.credential_command
    replacement = BrokerConnectionData({**dict(CREDS), "marker": "replacement"})

    async def interrupt(proc, command, update_id, credentials=None):
        await real_command(proc, command, update_id, credentials)
        if command == phase:
            if failure == "cancel":
                raise asyncio.CancelledError()
            raise ConnectionError("ack lost")

    monkeypatch.setattr(_manager, "credential_command", interrupt)
    with pytest.raises(asyncio.CancelledError if failure == "cancel" else RpcError):
        await sup._manager.reconnect(record.meta.id, auth_blob=replacement)
    assert record.broker is None
    assert proc.returncode is not None
    assert record.state == "broken"
    assert saved(sup, record) == (replacement if phase == "activate_credentials" else CREDS)
    monkeypatch.setattr(_manager, "credential_command", real_command)
    await sup.stop()
    await sup.start()
    assert sup._registry.get(record.meta.id).state == "running"


async def test_credential_commands_not_callable_on_tool_socket(running):
    sup, record = running
    for command in ("prepare_credentials", "activate_credentials", "discard_credentials"):
        result = await _rpc_call(record.broker.socket_path, command, {"credentials": {"TEST_TOKEN": "wrong"}})
        assert result["error"]["code"] == "BAD_REQUEST"
    assert "result" in await _rpc_call(record.broker.socket_path, GET, {})


async def test_grant_edit_waits_for_credential_update(running, monkeypatch):
    sup, record = running
    entered, release = asyncio.Event(), asyncio.Event()
    real_command = _manager.credential_command

    async def pause(proc, command, update_id, credentials=None):
        await real_command(proc, command, update_id, credentials)
        if command == "prepare_credentials":
            entered.set()
            await release.wait()

    monkeypatch.setattr(_manager, "credential_command", pause)
    reconnect = asyncio.create_task(sup._manager.reconnect(record.meta.id, auth_blob=CREDS))
    update = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        update = asyncio.create_task(sup._manager.update(record.meta.id, operation_grants=frozenset({GET})))
        await asyncio.sleep(.01)
        assert not update.done()
        release.set()
        await asyncio.wait_for(asyncio.gather(reconnect, update), 2)
        assert record.meta.agent_operation_grants == frozenset({GET})
        assert (await _rpc_call(record.broker.socket_path, SET, {"value": "no"}))["error"]["code"] == "PERMISSION_DENIED"
    finally:
        release.set()
        await asyncio.gather(reconnect, *([update] if update else []), return_exceptions=True)


async def test_failed_storage_recovery_stops_the_broker(running, monkeypatch):
    sup, record = running
    proc = record.broker.proc

    def broken_storage(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr(_manager, "write_meta", broken_storage)
    with pytest.raises(RpcError, match="credential recovery failed"):
        await sup._manager.reconnect(record.meta.id, auth_blob=CREDS)
    assert record.broker is None
    assert record.state == "broken"
    assert proc.returncode is not None


async def test_http_live_update_uses_new_token_and_rejects_invalid_config(tmp_path):
    seen = []

    async def upstream_handler(request):
        seen.append(request.headers.get("Authorization"))
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_get("/", upstream_handler)
    async with TestServer(app) as upstream:
        sup = Supervisor(
            vault_dir=tmp_path / "vault", app_sock_path=tmp_path / "app.sock",
            sockets_dir=tmp_path / "sockets", host_paths=make_host_paths(tmp_path),
            catalog={"http": build_integration_catalog()["http"]},
        )
        await sup.start()
        try:
            auth = {"base_url": str(upstream.make_url("/")), "header_name": "Authorization",
                    "header_template": "Bearer {token}", "token": "old"}
            added = await _rpc_call(sup.app_sock_path, "add", {
                "slug": "http", "label": "local", "auth_blob": auth, "operation_grants": ["http.request"],
            })
            record = sup._registry.get(added["result"]["id"])
            proc = record.broker.proc
            await _rpc_call(record.broker.socket_path, "http.request", {"method": "GET", "path": "/"})
            await sup._manager.reconnect(record.meta.id, auth_blob=BrokerConnectionData({**auth, "token": "new"}))
            assert record.broker.proc is proc
            await _rpc_call(record.broker.socket_path, "http.request", {"method": "GET", "path": "/"})
            with pytest.raises(RpcError) as rejected:
                await sup._manager.reconnect(record.meta.id, auth_blob=BrokerConnectionData({**auth, "base_url": "invalid"}))
            assert rejected.value.code == "BAD_REQUEST"
            assert record.broker.proc is proc
            await _rpc_call(record.broker.socket_path, "http.request", {"method": "GET", "path": "/"})
            assert seen == ["Bearer old", "Bearer new", "Bearer new"]
        finally:
            await sup.stop()
