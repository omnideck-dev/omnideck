"""Brokerless reconnect starts once, saves after READY, and cleans up failures."""

import asyncio

import pytest

from brokering._rpc import RpcError
from brokering.connection_data import BrokerConnectionData
from brokering.supervisor import _manager, _spawn, _store
from tests.integration.brokering.supervisor.test_live_grants import CREDS, GET, SET, running
from tests.integration.brokering.supervisor.test_supervisor import _rpc_call

REPLACEMENT = BrokerConnectionData({**dict(CREDS), "marker": "replacement"})


@pytest.fixture
async def degraded(running):
    sup, record = running
    await sup._manager.update(record.meta.id, operation_grants=frozenset({GET}))
    await sup._manager._stop_record_broker(record)
    record.state = "broken"
    return sup, record


def saved(sup, record):
    return _store.read_secrets(sup.vault_dir, record.meta.id, sup._manager._master_key)


async def test_ready_precedes_persistence_and_reconnect_survives_restart(degraded, monkeypatch):
    sup, record = degraded
    old_meta = record.meta
    real_spawn = _manager.spawn_broker
    candidates = []

    async def observe_ready(**kwargs):
        handle = await real_spawn(**kwargs)
        candidates.append(handle)
        assert saved(sup, record) == CREDS
        assert _store.read_raw_meta(sup.vault_dir, record.meta.id) == old_meta.model_dump(mode="json")
        assert record.broker is None
        return handle

    monkeypatch.setattr(_manager, "spawn_broker", observe_ready)
    await sup._manager.reconnect(record.meta.id, auth_blob=REPLACEMENT)
    assert len(candidates) == 1
    assert record.broker is candidates[0]
    assert record.state == "running"
    assert not record.expected_termination
    assert record.meta.id == old_meta.id
    assert record.meta.agent_operation_grants == frozenset({GET})
    assert record.meta.updated_at > old_meta.updated_at
    assert saved(sup, record) == REPLACEMENT
    assert (await _rpc_call(record.broker.socket_path, SET, {"value": "denied"}))["error"]["code"] == "PERMISSION_DENIED"
    monkeypatch.setattr(_manager, "spawn_broker", real_spawn)
    await sup.stop()
    await sup.start()
    restored = sup._registry.get(record.meta.id)
    assert restored.state == "running"
    assert restored.meta.agent_operation_grants == frozenset({GET})
    assert saved(sup, restored) == REPLACEMENT


async def test_rejected_startup_does_not_save_or_retry_old_credentials(degraded, monkeypatch):
    sup, record = degraded
    old_meta = record.meta
    old_ciphertext = _store.enc_path(sup.vault_dir, record.meta.id).read_bytes()
    real_spawn = _manager.spawn_broker
    attempts = []

    async def observe_attempt(**kwargs):
        attempts.append(kwargs["secret_bundle"])
        return await real_spawn(**kwargs)

    monkeypatch.setattr(_manager, "spawn_broker", observe_attempt)
    rejected = BrokerConnectionData({"token": "wrong-secret"})
    with pytest.raises(RpcError) as failure:
        await sup._manager.reconnect(record.meta.id, auth_blob=rejected)
    assert failure.value.code == "AUTH"
    assert attempts == [rejected]
    assert record.broker is None and record.state == "auth_failed"
    assert record.meta == old_meta
    assert record.meta.id not in sup._manager._watchers
    assert _store.enc_path(sup.vault_dir, record.meta.id).read_bytes() == old_ciphertext
    assert _store.read_raw_meta(sup.vault_dir, record.meta.id) == old_meta.model_dump(mode="json")
    # A failed reconnect leaves the same record available for an explicit retry.
    await sup._manager.reconnect(record.meta.id, auth_blob=REPLACEMENT)
    assert record.state == "running"
    assert saved(sup, record) == REPLACEMENT


@pytest.mark.parametrize("failed_file", [".meta", ".enc"])
async def test_save_failure_stops_candidate_without_fallback(degraded, monkeypatch, failed_file):
    sup, record = degraded
    old_meta = record.meta
    real_spawn = _manager.spawn_broker
    real_write = _store._atomic_write
    candidates = []

    async def observe_candidate(**kwargs):
        handle = await real_spawn(**kwargs)
        candidates.append(handle)
        return handle

    def fail_save(path, data, **kwargs):
        if path.suffix == failed_file:
            raise OSError("disk full")
        return real_write(path, data, **kwargs)

    monkeypatch.setattr(_manager, "spawn_broker", observe_candidate)
    monkeypatch.setattr(_store, "_atomic_write", fail_save)
    with pytest.raises(RpcError, match="could not save") as failure:
        await sup._manager.reconnect(record.meta.id, auth_blob=REPLACEMENT)
    assert failure.value.code == "INTERNAL"
    assert len(candidates) == 1
    assert candidates[0].proc.returncode is not None
    assert record.broker is None and record.state == "broken"
    assert record.meta == old_meta
    assert record.meta.id not in sup._manager._watchers
    assert saved(sup, record) == CREDS
    assert _store.read_raw_meta(sup.vault_dir, record.meta.id) == old_meta.model_dump(mode="json")


async def test_failed_timestamp_restore_still_stops_candidate_and_keeps_credentials(degraded, monkeypatch):
    sup, record = degraded
    real_spawn = _manager.spawn_broker
    real_write = _store._atomic_write
    candidates = []
    writes = 0

    async def observe_candidate(**kwargs):
        handle = await real_spawn(**kwargs)
        candidates.append(handle)
        return handle

    def fail_after_metadata(path, data, **kwargs):
        nonlocal writes
        writes += 1
        if writes > 1:
            raise OSError("disk unavailable")
        return real_write(path, data, **kwargs)

    monkeypatch.setattr(_manager, "spawn_broker", observe_candidate)
    monkeypatch.setattr(_store, "_atomic_write", fail_after_metadata)
    with pytest.raises(RpcError, match="could not save"):
        await sup._manager.reconnect(record.meta.id, auth_blob=REPLACEMENT)
    assert writes == 3  # Metadata, failed credential write, failed timestamp restore.
    assert len(candidates) == 1
    assert candidates[0].proc.returncode is not None
    assert record.broker is None and record.state == "broken"
    assert saved(sup, record) == CREDS
    assert _store.read_raw_meta(sup.vault_dir, record.meta.id)["agent_operation_grants"] == [GET]


@pytest.mark.parametrize("failure", ["cancel", "timeout", "read_error"])
async def test_interrupted_startup_reaps_child_without_saving(degraded, monkeypatch, failure):
    sup, record = degraded
    old_meta = record.meta
    entered = asyncio.Event()
    children = []

    async def blocked_ready(proc):
        children.append(proc)
        entered.set()
        if failure == "read_error":
            raise ValueError("invalid readiness stream")
        await asyncio.Event().wait()

    monkeypatch.setattr(_spawn, "_wait_for_ready", blocked_ready)
    if failure == "timeout":
        monkeypatch.setattr(_spawn, "_READY_TIMEOUT_SECONDS", 0.1)
    task = asyncio.create_task(sup._manager.reconnect(record.meta.id, auth_blob=REPLACEMENT))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        if failure == "cancel":
            task.cancel()
        with pytest.raises(asyncio.CancelledError if failure == "cancel" else RpcError):
            await asyncio.wait_for(task, 5)
        assert len(children) == 1
        assert children[0].returncode is not None
        assert record.broker is None and record.state == "broken"
        assert record.meta.id not in sup._manager._watchers
        assert saved(sup, record) == CREDS
        assert _store.read_raw_meta(sup.vault_dir, record.meta.id) == old_meta.model_dump(mode="json")
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_degraded_reconnect_can_replace_unreadable_old_credentials(degraded):
    sup, record = degraded
    _store.enc_path(sup.vault_dir, record.meta.id).write_bytes(b"corrupt ciphertext")
    await sup._manager.reconnect(record.meta.id, auth_blob=REPLACEMENT)
    assert record.state == "running"
    assert saved(sup, record) == REPLACEMENT
