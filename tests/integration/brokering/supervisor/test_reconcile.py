"""End-to-end tests for ``Supervisor`` startup reconciliation.

Each test stages a vault by running one supervisor (the "first boot"),
stops it, then starts a second supervisor against the same vault dir and
asserts what the second one rehydrates. Both supervisors talk to a real
``FakeEmail`` broker, so the spawn / IMAP-login / READY handshake
exercises the production path end-to-end.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from integrations.operations import OPERATIONS_BY_GROUP

import pytest

from brokering.catalog import CatalogEntry
from brokering.supervisor._crypto import load_or_init_master_key
from brokering.supervisor._lifecycle import Supervisor
from brokering.supervisor._store import (
    enc_path,
    meta_backup_path,
    meta_path,
    read_raw_meta,
    write_secrets,
)
from brokering.supervisor.types import IntegrationConnectionMeta
from tests.integration.integrations.fixtures._catalog import make_fake_email_catalog
from tests.integration.integrations.fixtures._host_paths import make_host_paths
from tests.integration.integrations.fixtures.fake_email import FakeEmail


async def _rpc_call(socket_path: Path, verb: str, args: dict[str, Any]) -> dict[str, Any]:
    """Length-prefixed JSON RPC: open, send, read, close."""
    reader, writer = await asyncio.open_unix_connection(str(socket_path))
    try:
        req = json.dumps({"id": 1, "verb": verb, "args": args}).encode("utf-8")
        writer.write(len(req).to_bytes(4, "big") + req)
        await writer.drain()
        length = int.from_bytes(await reader.readexactly(4), "big")
        return json.loads(await reader.readexactly(length))
    finally:
        writer.close()
        await writer.wait_closed()


def _test_catalog(fake: FakeEmail) -> dict[str, CatalogEntry]:
    """A catalog with one ``icloud`` entry pointed at the local fake."""
    return make_fake_email_catalog(fake)


def _make_supervisor(tmp_path: Path, catalog: dict[str, CatalogEntry]) -> Supervisor:
    """Build a Supervisor that points at ``tmp_path``-relative vault + sockets.

    Both supervisors in a reconcile test reuse the same ``tmp_path``, so the
    vault on disk persists across the stop / start boundary while the
    sockets dir is wiped tmpfs-style by the second supervisor.
    """
    return Supervisor(
        vault_dir=tmp_path / "vault",
        app_sock_path=tmp_path / "app.sock",
        sockets_dir=tmp_path / "sockets",
        host_paths=make_host_paths(tmp_path),
        catalog=catalog,
    )


@pytest.mark.parametrize("version", [2, 3])
async def test_startup_preserves_grants_despite_narrower_scope_availability(tmp_path, version):
    """Neither metadata migration nor later restarts may scope-filter user intent."""
    fake = FakeEmail()
    await fake.start()
    try:
        base = make_fake_email_catalog(fake)["icloud"]
        readable = frozenset({"email.mailboxes.list"})
        entry = replace(base, operations=frozenset(), scope_operations={
            "full": OPERATIONS_BY_GROUP["email"], "limited": readable,
        })
        iid = "icloud_personal"
        now = datetime.now(UTC)
        selected = (
            OPERATIONS_BY_GROUP["email"] if version == 2
            else frozenset({"email.mailboxes.list", "email.messages.send"})
        )
        raw = IntegrationConnectionMeta(
            id=iid, slug="icloud", label="Personal", added_at=now, updated_at=now,
            agent_operation_grants=selected,
        ).model_dump(mode="json")
        if version == 2:
            raw.pop("agent_operation_grants")
            raw.pop("kind")
            raw.update(version=2, permissions={"email": "rw"})
        vault = tmp_path / "vault"
        path = meta_path(vault, iid)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(raw), encoding="utf-8")
        key = load_or_init_master_key(vault)
        write_secrets(vault, iid, key, {
            "email": fake.user, "password": fake.password, "scopes": "limited",
        })
        encrypted = enc_path(vault, iid).read_bytes()
        for _ in range(2):
            supervisor = _make_supervisor(tmp_path, {"icloud": entry})
            await supervisor.start()
            try:
                response = await _rpc_call(supervisor.app_sock_path, "list", {})
                [record] = response["result"]["connections"]
                assert record["operation_grants"] == sorted(selected)
                assert record["available_operation_ids"] == sorted(readable)
                assert {op["id"] for op in record["operations"]} == readable
                # The real broker receives the grant despite configuration
                # not offering it. This local SMTP fake accepts the request.
                sent = await _rpc_call(Path(record["socket"]), "email.messages.send", {
                    "to": ["recipient@example.com"], "subject": "Test", "body": "Local only",
                })
                assert "error" not in sent, sent
                denied = await _rpc_call(Path(record["socket"]), "calendar.calendars.list", {})
                assert denied["error"]["code"] == "PERMISSION_DENIED"
                assert read_raw_meta(vault, iid)["agent_operation_grants"] == sorted(selected)
                assert enc_path(vault, iid).read_bytes() == encrypted
            finally:
                await supervisor.stop()
    finally:
        await fake.stop()


@pytest.mark.asyncio
async def test_reconcile_migrates_v2_grants_with_backup_and_broker_enforcement(
    tmp_path: Path,
) -> None:
    fake = FakeEmail()
    await fake.start()
    vault = tmp_path / "vault"
    connection_id = "icloud_personal"
    original = {
        "version": 2,
        "id": connection_id,
        "slug": "icloud",
        "label": "Legacy iCloud",
        "permissions": {"email": "r", "calendar": "off"},
        "added_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    path = meta_path(vault, connection_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(original), encoding="utf-8")
    key = load_or_init_master_key(vault)
    write_secrets(vault, connection_id, key, {
        "email": fake.user,
        "password": fake.password,
    })

    supervisor = _make_supervisor(tmp_path, _test_catalog(fake))
    await supervisor.start()
    try:
        migrated = read_raw_meta(vault, connection_id)
        assert migrated["version"] == 3
        assert migrated["kind"] == "integration"
        assert migrated["agent_operation_grants"] == [
            "email.attachments.download",
            "email.mailboxes.list",
            "email.messages.get",
            "email.messages.list",
            "email.messages.search",
        ]
        assert json.loads(meta_backup_path(vault, connection_id).read_text()) == original

        socket = supervisor._registry.get(connection_id).broker.socket_path
        allowed = await _rpc_call(socket, "email.mailboxes.list", {})
        assert "error" not in allowed
        denied = await _rpc_call(
            socket,
            "email.messages.send",
            {"to": ["a@example.com"], "subject": "x", "body": "y"},
        )
        assert denied["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await supervisor.stop()
        await fake.stop()


async def test_failed_migration_prevents_broker_start_and_listener(tmp_path):
    supervisor = _make_supervisor(tmp_path, {})
    path = meta_path(supervisor.vault_dir, "gmail_example")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "version": 2, "id": "gmail_example", "slug": "gmail",
        "permissions": {"email": "invalid"},
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="Cannot migrate"):
        await supervisor.start()
    assert not supervisor.app_sock_path.exists()
    assert supervisor._manager is None
    assert not (supervisor.vault_dir / ".migrations.json").exists()
    await supervisor.stop()


@pytest.mark.asyncio
async def test_reconcile_respawns_persisted_integration(tmp_path: Path) -> None:
    """Add → stop → restart → the integration is back without re-add.

    Proves the load-bearing claim: container restart no longer loses the
    user's connections. After the second supervisor's start() returns,
    ``list`` surfaces the same id and the broker socket is reachable.
    """
    fake = FakeEmail()
    await fake.start()
    try:
        sup1 = _make_supervisor(tmp_path, _test_catalog(fake))
        await sup1.start()
        try:
            add_resp = await _rpc_call(
                sup1.app_sock_path,
                "add",
                {
                    "slug": "icloud",
                    "user_suffix": "personal",
                    "label": "iCloud test",
                    "auth_blob": {"email": fake.user, "password": fake.password},
                    "operation_grants": sorted(OPERATIONS_BY_GROUP["email"] | OPERATIONS_BY_GROUP["calendar"]),
                },
            )
            assert "error" not in add_resp, add_resp
        finally:
            await sup1.stop()

        # Vault files persist; broker subprocess is gone.
        assert meta_path(sup1.vault_dir, "icloud_personal").exists()
        assert enc_path(sup1.vault_dir, "icloud_personal").exists()

        sup2 = _make_supervisor(tmp_path, _test_catalog(fake))
        await sup2.start()
        try:
            # Registry is rehydrated — list shows the integration.
            list_resp = await _rpc_call(sup2.app_sock_path, "list", {})
            integrations = list_resp["result"]["connections"]
            assert len(integrations) == 1
            assert integrations[0]["id"] == "icloud_personal"

            # Broker is up — calling list_mailboxes against its socket works.
            broker_socket = Path(integrations[0]["socket"])
            assert broker_socket.exists()
            mb_resp = await _rpc_call(broker_socket, "email.mailboxes.list", {})
            assert "error" not in mb_resp, mb_resp
            assert sorted(m["name"] for m in mb_resp["result"]["mailboxes"]) == [
                "INBOX",
                "Sent",
                "Trash",
            ]
        finally:
            await sup2.stop()
    finally:
        await fake.stop()


@pytest.mark.asyncio
async def test_reconcile_skips_integration_when_slug_missing_from_catalog(
    tmp_path: Path,
) -> None:
    """Catalog drift (slug removed) → that integration is skipped, others load.

    The vault entry stays on disk so the user can re-add (or a future
    catalog can re-introduce the slug) without losing credentials.
    """
    fake = FakeEmail()
    await fake.start()
    try:
        sup1 = _make_supervisor(tmp_path, _test_catalog(fake))
        await sup1.start()
        try:
            add_resp = await _rpc_call(
                sup1.app_sock_path,
                "add",
                {
                    "slug": "icloud",
                    "user_suffix": "personal",
                    "label": "iCloud test",
                    "auth_blob": {"email": fake.user, "password": fake.password},
                    "operation_grants": sorted(OPERATIONS_BY_GROUP["email"] | OPERATIONS_BY_GROUP["calendar"]),
                },
            )
            assert "error" not in add_resp, add_resp
        finally:
            await sup1.stop()

        # Second supervisor with an empty catalog — slug "icloud" is gone.
        sup2 = _make_supervisor(tmp_path, {})
        await sup2.start()
        try:
            list_resp = await _rpc_call(sup2.app_sock_path, "list", {})
            assert list_resp["result"]["connections"] == []
        finally:
            await sup2.stop()

        # Vault files weren't deleted — credentials are preserved.
        assert meta_path(sup1.vault_dir, "icloud_personal").exists()
        assert enc_path(sup1.vault_dir, "icloud_personal").exists()
    finally:
        await fake.stop()


@pytest.mark.asyncio
async def test_reconcile_retains_auth_failed_integration_for_reconnect(
    tmp_path: Path,
) -> None:
    """Upstream auth failure remains visible and can be reconnected.

    Mirrors the real-world case where a user's app-password gets rotated
    out from under us. The supervisor stays up; the user's path forward
    is to reconnect through the UI.
    """
    fake = FakeEmail()
    await fake.start()
    try:
        sup1 = _make_supervisor(tmp_path, _test_catalog(fake))
        await sup1.start()
        try:
            add_resp = await _rpc_call(
                sup1.app_sock_path,
                "add",
                {
                    "slug": "icloud",
                    "user_suffix": "personal",
                    "label": "iCloud test",
                    "auth_blob": {"email": fake.user, "password": fake.password},
                    "operation_grants": sorted(OPERATIONS_BY_GROUP["email"] | OPERATIONS_BY_GROUP["calendar"]),
                },
            )
            assert "error" not in add_resp, add_resp
        finally:
            await sup1.stop()

        # Make every subsequent IMAP LOGIN fail — reconcile's broker spawn
        # will exit 77 (auth fail) and we should swallow that gracefully.
        fake.reject_next_n_imap_logins = 99

        sup2 = _make_supervisor(tmp_path, _test_catalog(fake))
        await sup2.start()
        try:
            list_resp = await _rpc_call(sup2.app_sock_path, "list", {})
            [record] = list_resp["result"]["connections"]
            assert record["id"] == "icloud_personal"
            assert record["state"] == "auth_failed"
            assert record["socket"] is None

            fake.reject_next_n_imap_logins = 0
            reconnect = await _rpc_call(
                sup2.app_sock_path,
                "reconnect",
                {
                    "id": "icloud_personal",
                    "kind": "integration",
                    "auth_blob": {"email": fake.user, "password": fake.password},
                },
            )
            assert reconnect["result"]["state"] == "running"
            assert reconnect["result"]["socket"]
        finally:
            await sup2.stop()

        # Reconnect preserves the same vault identity.
        assert meta_path(sup1.vault_dir, "icloud_personal").exists()
        assert enc_path(sup1.vault_dir, "icloud_personal").exists()
    finally:
        await fake.stop()
