"""Real subprocess grant control, persistence, and lifecycle serialization."""

import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from brokering._rpc import RpcError
from brokering.connection_data import BrokerConnectionData
from brokering.supervisor import _manager
from brokering.supervisor._lifecycle import Supervisor
from brokering.supervisor._store import read_raw_meta
from integrations.catalog import build_integration_catalog
from tests.integration.brokering.supervisor.test_supervisor import _rpc_call
from tests.integration.integrations.fixtures._host_paths import make_host_paths

GET = "test.value.get"
SET = "test.value.set"
CREDS = BrokerConnectionData({"token": "omnideck-test-token"})


@pytest.fixture
async def running(tmp_path):
    sup = Supervisor(
        vault_dir=tmp_path / "vault", app_sock_path=tmp_path / "app.sock",
        sockets_dir=tmp_path / "sockets", host_paths={},
        catalog={"test": build_integration_catalog(include_test_integrations=True)["test"]},
    )
    await sup.start()
    try:
        added = await _rpc_call(sup.app_sock_path, "add", {
            "slug": "test", "label": "test", "auth_blob": dict(CREDS),
            "operation_grants": [GET, SET],
        })
        assert "error" not in added, added
        record = sup._registry.get(added["result"]["id"])
        yield sup, record
    finally:
        await sup.stop()


async def test_live_revocation_keeps_pid_state_and_survives_restart(running):
    sup, record = running
    pid, socket = record.broker.proc.pid, record.broker.socket_path
    await _rpc_call(socket, SET, {"value": "retained"})
    updated = await _rpc_call(sup.app_sock_path, "update", {
        "id": record.meta.id, "operation_grants": [GET],
    })
    assert "error" not in updated, updated
    assert record.broker.proc.pid == pid
    assert (await _rpc_call(socket, GET, {}))["result"]["value"] == "retained"
    assert (await _rpc_call(socket, SET, {"value": "denied"}))["error"]["code"] == "PERMISSION_DENIED"
    assert read_raw_meta(sup.vault_dir, record.meta.id)["agent_operation_grants"] == [GET]
    await sup.stop()
    await sup.start()
    restored = sup._registry.get(record.meta.id)
    assert restored.broker.proc.pid != pid
    assert (await _rpc_call(restored.broker.socket_path, SET, {"value": "denied"}))["error"]["code"] == "PERMISSION_DENIED"


async def test_tool_socket_cannot_change_grants(running):
    sup, record = running
    await sup._manager.update(record.meta.id, operation_grants=frozenset({GET}))
    for verb in ("update_grants", "set_grants", "grants"):
        response = await _rpc_call(record.broker.socket_path, verb, {"grants": [GET, SET]})
        assert response["error"]["code"] == "BAD_REQUEST"
    response = await _rpc_call(record.broker.socket_path, SET, {"value": "no", "grants": [SET]})
    assert response["error"]["code"] == "PERMISSION_DENIED"


async def test_http_inflight_request_finishes_but_later_calls_are_revoked(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow(request):
        entered.set()
        await release.wait()
        return web.json_response({"finished": True})

    app = web.Application()
    app.router.add_get("/slow", slow)
    async with TestServer(app) as upstream:
        sup = Supervisor(
            vault_dir=tmp_path / "vault", app_sock_path=tmp_path / "app.sock",
            sockets_dir=tmp_path / "sockets", host_paths=make_host_paths(tmp_path),
            catalog={"http": build_integration_catalog()["http"]},
        )
        await sup.start()
        request_task = None
        try:
            added = await _rpc_call(sup.app_sock_path, "add", {
                "slug": "http", "label": "local", "operation_grants": ["http.request"],
                "auth_blob": {"base_url": str(upstream.make_url("/")), "header_name": "Authorization",
                              "header_template": "Bearer {token}", "token": "local"},
            })
            assert "error" not in added, added
            record = sup._registry.get(added["result"]["id"])
            proc = record.broker.proc
            socket = record.broker.socket_path
            request_task = asyncio.create_task(_rpc_call(socket, "http.request", {"method": "GET", "path": "/slow"}))
            await asyncio.wait_for(entered.wait(), 2)
            await asyncio.wait_for(sup._manager.update(record.meta.id, operation_grants=frozenset()), 2)
            assert record.broker.proc is proc
            assert not request_task.done()
            denied = await _rpc_call(socket, "http.request", {"method": "GET", "path": "/slow"})
            assert denied["error"]["code"] == "PERMISSION_DENIED"
            release.set()
            response = await asyncio.wait_for(request_task, 2)
            assert response["result"]["status"] == 200
        finally:
            release.set()
            if request_task is not None:
                await asyncio.gather(request_task, return_exceptions=True)
            await sup.stop()


async def test_lost_ack_stops_broker_and_keeps_revocation(running, monkeypatch):
    sup, record = running
    proc = record.broker.proc
    real_update = _manager.update_broker_grants

    async def lose_ack(proc, grants):
        await real_update(proc, grants)
        raise TimeoutError("acknowledgement lost")

    monkeypatch.setattr(_manager, "update_broker_grants", lose_ack)
    with pytest.raises(RpcError, match="reconnect required"):
        await sup._manager.update(record.meta.id, operation_grants=frozenset({GET}))
    assert proc.returncode is not None
    assert record.broker is None and record.state == "broken"
    assert read_raw_meta(sup.vault_dir, record.meta.id)["agent_operation_grants"] == [GET]
    await sup.stop()
    await sup.start()
    restored = sup._registry.get(record.meta.id)
    assert (await _rpc_call(restored.broker.socket_path, SET, {"value": "no"}))["error"]["code"] == "PERMISSION_DENIED"


async def test_persistence_failure_stops_broker_before_control_send(running, monkeypatch):
    sup, record = running
    proc = record.broker.proc

    def fail_write(*args):
        raise OSError("disk unavailable")

    async def unexpected_send(*args):
        raise AssertionError("must persist before applying")

    monkeypatch.setattr(_manager, "write_meta", fail_write)
    monkeypatch.setattr(_manager, "update_broker_grants", unexpected_send)
    with pytest.raises(RpcError, match="persist"):
        await sup._manager.update(record.meta.id, operation_grants=frozenset({GET}))
    assert proc.returncode is not None
    assert record.broker is None and record.state == "broken"


async def test_cancelled_handoff_stops_broker_and_keeps_saved_policy(running, monkeypatch):
    sup, record = running
    proc = record.broker.proc
    entered = asyncio.Event()

    async def blocked(*args):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(_manager, "update_broker_grants", blocked)
    task = asyncio.create_task(sup._manager.update(record.meta.id, operation_grants=frozenset({GET})))
    try:
        await asyncio.wait_for(entered.wait(), 2)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert proc.returncode is not None
    assert record.broker is None
    assert read_raw_meta(sup.vault_dir, record.meta.id)["agent_operation_grants"] == [GET]


@pytest.mark.parametrize("next_action", ["update", "reconnect", "remove"])
async def test_handoff_serializes_with_other_mutations(running, monkeypatch, next_action):
    sup, record = running
    entered, release = asyncio.Event(), asyncio.Event()
    real_update = _manager.update_broker_grants

    async def blocked(proc, grants):
        entered.set()
        await release.wait()
        await real_update(proc, grants)

    monkeypatch.setattr(_manager, "update_broker_grants", blocked)
    first = asyncio.create_task(sup._manager.update(record.meta.id, operation_grants=frozenset({GET})))
    second = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        if next_action == "update":
            work = sup._manager.update(record.meta.id, operation_grants=frozenset())
        elif next_action == "reconnect":
            work = sup._manager.reconnect(record.meta.id, auth_blob=CREDS)
        else:
            work = sup._manager.remove(record.meta.id)
        second = asyncio.create_task(work)
        await asyncio.sleep(0)
        assert not second.done()
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(first, *([second] if second else [])), 5)
    if next_action == "remove":
        assert sup._registry.get(record.meta.id) is None
    else:
        expected = frozenset() if next_action == "update" else frozenset({GET})
        assert record.meta.agent_operation_grants == expected
        assert (await _rpc_call(record.broker.socket_path, SET, {"value": "no"}))["error"]["code"] == "PERMISSION_DENIED"
