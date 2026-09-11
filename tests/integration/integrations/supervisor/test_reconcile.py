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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from integrations.catalog import CatalogEntry
from integrations.supervisor._crypto import load_or_init_master_key
from integrations.supervisor._lifecycle import Supervisor
from integrations.supervisor._store import (
    enc_path,
    meta_backup_path,
    meta_path,
    read_raw_meta,
    write_secrets,
)
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


@pytest.mark.asyncio
async def test_reconcile_migrates_v2_grants_with_backup_and_broker_enforcement(
    tmp_path: Path,
) -> None:
    fake = FakeEmail()
    await fake.start()
    vault = tmp_path / "vault"
    integration_id = "icloud_personal"
    original = {
        "version": 2,
        "id": integration_id,
        "slug": "icloud",
        "label": "Legacy iCloud",
        "permissions": {"email": "r", "calendar": "off"},
        "added_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    path = meta_path(vault, integration_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(original), encoding="utf-8")
    key = load_or_init_master_key(vault)
    write_secrets(vault, integration_id, key, {
        "email": fake.user,
        "password": fake.password,
    })

    supervisor = _make_supervisor(tmp_path, _test_catalog(fake))
    await supervisor.start()
    try:
        migrated = read_raw_meta(vault, integration_id)
        assert migrated["version"] == 3
        assert migrated["kind"] == "integration"
        assert migrated["agent_operation_grants"] == [
            "email.attachments.download",
            "email.mailboxes.list",
            "email.messages.get",
            "email.messages.list",
            "email.messages.search",
        ]
        assert json.loads(meta_backup_path(vault, integration_id).read_text()) == original

        socket = supervisor._registry.get(integration_id).broker.socket_path
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
                    "permissions": {"email": "rw", "calendar": "rw"},
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
            integrations = list_resp["result"]["integrations"]
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
                    "permissions": {"email": "rw", "calendar": "rw"},
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
            assert list_resp["result"]["integrations"] == []
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
                    "permissions": {"email": "rw", "calendar": "rw"},
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
            [record] = list_resp["result"]["integrations"]
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
