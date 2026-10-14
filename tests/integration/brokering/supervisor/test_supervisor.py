"""End-to-end integration tests for the supervisor and email broker.

Exercises the whole vertical slice in one test:

- Start a real ``Supervisor`` instance in-process with a ``tmp_path`` vault.
- Inject a test catalog that points the email_broker at ``FakeEmail``'s random
  ports with TLS off, so we use the real broker binary against a local fake.
- Call ``add`` over the supervisor's ``app.sock`` — this causes the supervisor
  to write vault files, spawn a real ``python -m brokering.brokers.email_broker``
  subprocess, wait for its ``READY`` sentinel, and register it.
- Call ``resolve`` to get the broker's UDS path back from the supervisor.
- Call ``email.mailboxes.list`` directly against that broker — proves the app-server
  side of the flow (broker_client will replicate this call shape).
- Call ``list`` and ``remove`` on the supervisor; verify the broker dies and
  vault files disappear.

Nothing mocked at the socket layer. Fakes only at the external-network boundary.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from integrations.operations import OPERATIONS_BY_GROUP

import pytest

from brokering.catalog import CatalogEntry
from brokering.brokers.llm_proxy.catalog import ModelProviderCatalogEntry
from brokering.drivers import BrokerDriver
from brokering.supervisor._lifecycle import Supervisor
from brokering.supervisor._store import enc_path, meta_path, read_raw_meta
from tests.integration.integrations.fixtures._catalog import make_fake_email_catalog
from tests.integration.integrations.fixtures._host_paths import make_host_paths
from tests.integration.integrations.fixtures.fake_email import FakeEmail


async def _rpc_call(socket_path: Path, verb: str, args: dict[str, Any]) -> dict[str, Any]:
    """Send one length-prefixed JSON frame, read one response, close.

    Same wire format as the app server's ``broker_client`` will use — this helper
    is deliberately small so the test has no dependency on client-side code that
    hasn't been written yet.
    """
    reader, writer = await asyncio.open_unix_connection(str(socket_path))
    try:
        req = json.dumps({"id": 1, "verb": verb, "args": args}).encode("utf-8")
        writer.write(len(req).to_bytes(4, "big") + req)
        await writer.drain()
        length = int.from_bytes(await reader.readexactly(4), "big")
        body = await reader.readexactly(length)
        return json.loads(body)
    finally:
        writer.close()
        await writer.wait_closed()


def _test_catalog(fake: FakeEmail) -> dict[str, CatalogEntry]:
    """Build a catalog that points the email broker at ``fake``'s random ports.

    Equivalent to the real iCloud catalog entry, but with the fake's host/port
    substituted in and TLS turned off — the fake speaks plaintext IMAP/SMTP.
    """
    return make_fake_email_catalog(fake)


@pytest.mark.asyncio
async def test_add_then_call_broker_then_resolve_then_remove(tmp_path: Path) -> None:
    """The full end-to-end slice: add -> call broker -> resolve -> list -> remove."""
    fake = FakeEmail()
    await fake.start()
    sup = Supervisor(
        vault_dir=tmp_path / "vault",
        app_sock_path=tmp_path / "app.sock",
        sockets_dir=tmp_path / "sockets",
        host_paths=make_host_paths(tmp_path),
        catalog=_test_catalog(fake),
    )
    await sup.start()
    try:
        # --- add ---
        add_resp = await _rpc_call(
            sup.app_sock_path,
            "add",
            {
                "slug": "icloud",
                "user_suffix": "personal",
                "label": "iCloud test",
                "auth_blob": {"email": fake.user, "password": fake.password},
                "operation_grants": sorted(OPERATIONS_BY_GROUP["email"] - {"email.messages.send", "email.messages.move"}),
            },
        )
        assert "error" not in add_resp, add_resp
        result = add_resp["result"]
        assert result["id"] == "icloud_personal"
        broker_socket = Path(result["socket"])
        assert broker_socket.exists()
        # Vault files landed on disk.
        assert meta_path(sup.vault_dir, "icloud_personal").exists()
        assert enc_path(sup.vault_dir, "icloud_personal").exists()

        # --- call broker directly ---
        mb_resp = await _rpc_call(broker_socket, "email.mailboxes.list", {})
        assert "error" not in mb_resp, mb_resp
        names = sorted(m["name"] for m in mb_resp["result"]["mailboxes"])
        assert names == ["INBOX", "Sent", "Trash"]

        # --- resolve returns the same socket ---
        resolve_resp = await _rpc_call(
            sup.app_sock_path, "resolve", {"id": "icloud_personal"},
        )
        assert resolve_resp["result"]["id"] == "icloud_personal"
        assert resolve_resp["result"]["socket"] == str(broker_socket)
        assert resolve_resp["result"]["operation_grants"] == sorted(OPERATIONS_BY_GROUP["email"] - {"email.messages.send", "email.messages.move"})

        # --- list surfaces the integration ---
        list_resp = await _rpc_call(sup.app_sock_path, "list", {})
        integrations = list_resp["result"]["connections"]
        assert len(integrations) == 1
        assert integrations[0]["id"] == "icloud_personal"
        assert integrations[0]["operation_grants"] == sorted(OPERATIONS_BY_GROUP["email"] - {"email.messages.send", "email.messages.move"})

        # --- remove kills the broker and deletes vault files ---
        remove_resp = await _rpc_call(
            sup.app_sock_path, "remove", {"id": "icloud_personal"},
        )
        assert remove_resp["result"] == {"id": "icloud_personal"}
        assert not meta_path(sup.vault_dir, "icloud_personal").exists()
        assert not enc_path(sup.vault_dir, "icloud_personal").exists()

        # --- resolve now returns NOT_FOUND ---
        resolve_after = await _rpc_call(
            sup.app_sock_path, "resolve", {"id": "icloud_personal"},
        )
        assert resolve_after["error"]["code"] == "NOT_FOUND"
    finally:
        await sup.stop()
        await fake.stop()


@pytest.mark.asyncio
async def test_add_with_bad_credentials_returns_auth_error(tmp_path: Path) -> None:
    """Broker LOGIN fails -> it exits 77 -> supervisor surfaces AUTH error and
    rolls back vault state so the user can retry cleanly.
    """
    fake = FakeEmail()
    await fake.start()
    # Force the next LOGIN to be rejected.
    fake.reject_next_n_imap_logins = 99
    sup = Supervisor(
        vault_dir=tmp_path / "vault",
        app_sock_path=tmp_path / "app.sock",
        sockets_dir=tmp_path / "sockets",
        host_paths=make_host_paths(tmp_path),
        catalog=_test_catalog(fake),
    )
    await sup.start()
    try:
        resp = await _rpc_call(
            sup.app_sock_path,
            "add",
            {
                "slug": "icloud",
                "user_suffix": "personal",
                "label": "iCloud bad",
                "auth_blob": {"email": fake.user, "password": "wrong"},
                "operation_grants": sorted(OPERATIONS_BY_GROUP["email"] | OPERATIONS_BY_GROUP["calendar"]),
            },
        )
        assert resp["error"]["code"] == "AUTH"
        # Rollback: no vault files should exist.
        assert not meta_path(sup.vault_dir, "icloud_personal").exists()
        assert not enc_path(sup.vault_dir, "icloud_personal").exists()
        # And the registry is empty.
        list_resp = await _rpc_call(sup.app_sock_path, "list", {})
        assert list_resp["result"]["connections"] == []
    finally:
        await sup.stop()
        await fake.stop()


@pytest.mark.asyncio
async def test_add_with_unknown_slug_returns_bad_request(tmp_path: Path) -> None:
    """A slug that's not in the injected catalog fails before any vault I/O."""
    fake = FakeEmail()
    await fake.start()
    sup = Supervisor(
        vault_dir=tmp_path / "vault",
        app_sock_path=tmp_path / "app.sock",
        sockets_dir=tmp_path / "sockets",
        host_paths=make_host_paths(tmp_path),
        catalog=_test_catalog(fake),
    )
    await sup.start()
    try:
        resp = await _rpc_call(
            sup.app_sock_path,
            "add",
            {
                "slug": "made_up_provider",
                "user_suffix": "x",
                "label": "x",
                "auth_blob": {},
                "operation_grants": sorted(OPERATIONS_BY_GROUP["email"]),
            },
        )
        assert resp["error"]["code"] == "BAD_REQUEST"
    finally:
        await sup.stop()
        await fake.stop()


@pytest.mark.asyncio
async def test_resolve_unknown_id_returns_not_found(tmp_path: Path) -> None:
    """Looking up an integration that was never added returns NOT_FOUND."""
    sup = Supervisor(
        vault_dir=tmp_path / "vault",
        app_sock_path=tmp_path / "app.sock",
        sockets_dir=tmp_path / "sockets",
        host_paths=make_host_paths(tmp_path),
        catalog={},  # empty catalog is fine; resolve doesn't touch it
    )
    await sup.start()
    try:
        resp = await _rpc_call(
            sup.app_sock_path, "resolve", {"id": "never_added"},
        )
        assert resp["error"]["code"] == "NOT_FOUND"
    finally:
        await sup.stop()


@pytest.mark.asyncio
async def test_update_changes_grants_without_restarting_broker(tmp_path: Path) -> None:
    """A live allowlist update enables sending without reconnecting upstream."""
    fake = FakeEmail()
    await fake.start()
    sup = Supervisor(
        vault_dir=tmp_path / "vault",
        app_sock_path=tmp_path / "app.sock",
        sockets_dir=tmp_path / "sockets",
        host_paths=make_host_paths(tmp_path),
        catalog=_test_catalog(fake),
    )
    await sup.start()
    try:
        add_resp = await _rpc_call(
            sup.app_sock_path,
            "add",
            {
                "slug": "icloud",
                "user_suffix": "personal",
                "label": "iCloud test",
                "auth_blob": {"email": fake.user, "password": fake.password},
                "operation_grants": sorted(OPERATIONS_BY_GROUP["email"] - {"email.messages.send", "email.messages.move"}),
            },
        )
        assert "error" not in add_resp, add_resp
        old_pid = sup._registry.get("icloud_personal").broker.proc.pid
        broker_socket_old = Path(add_resp["result"]["socket"])

        # Confirm the gate is currently active: send_message → PERMISSION_DENIED.
        denied = await _rpc_call(
            broker_socket_old,
            "email.messages.send",
            {"to": ["a@b.com"], "subject": "x", "body": "y"},
        )
        assert denied["error"]["code"] == "PERMISSION_DENIED"

        # Elevate the permissions.
        upd_resp = await _rpc_call(
            sup.app_sock_path,
            "update",
            {"id": "icloud_personal", "operation_grants": sorted(OPERATIONS_BY_GROUP["email"] | OPERATIONS_BY_GROUP["calendar"])},
        )
        assert "error" not in upd_resp, upd_resp
        assert upd_resp["result"]["operation_grants"] == sorted(OPERATIONS_BY_GROUP["email"] | OPERATIONS_BY_GROUP["calendar"])

        # The original broker and its upstream sessions remain in place.
        new_record = sup._registry.get("icloud_personal")
        assert new_record.broker.proc.pid == old_pid
        assert new_record.state == "running"

        # Same socket and process — the new permission gate passes now.
        broker_socket_new = Path(upd_resp["result"]["socket"])
        send_resp = await _rpc_call(
            broker_socket_new,
            "email.messages.send",
            {"to": ["a@b.com"], "subject": "x", "body": "y"},
        )
        assert "error" not in send_resp, send_resp
        assert send_resp["result"]["sent"] is True

        # On-disk meta reflects the new permissions — would survive restart.
        list_resp = await _rpc_call(sup.app_sock_path, "list", {})
        listed = next(
            i for i in list_resp["result"]["connections"]
            if i["id"] == "icloud_personal"
        )
        assert listed["operation_grants"] == sorted(OPERATIONS_BY_GROUP["email"] | OPERATIONS_BY_GROUP["calendar"])
    finally:
        await sup.stop()
        await fake.stop()


@pytest.mark.asyncio
async def test_update_unknown_id_returns_not_found(tmp_path: Path) -> None:
    """``update`` against an integration that doesn't exist is NOT_FOUND."""
    sup = Supervisor(
        vault_dir=tmp_path / "vault",
        app_sock_path=tmp_path / "app.sock",
        sockets_dir=tmp_path / "sockets",
        host_paths=make_host_paths(tmp_path),
        catalog={},
    )
    await sup.start()
    try:
        resp = await _rpc_call(
            sup.app_sock_path,
            "update",
            {"id": "never_added", "operation_grants": sorted(OPERATIONS_BY_GROUP["email"])},
        )
        assert resp["error"]["code"] == "NOT_FOUND"
    finally:
        await sup.stop()


@pytest.mark.asyncio
async def test_update_changes_label_via_app_sock(tmp_path: Path) -> None:
    """``update {id, label}`` rewrites the on-disk meta and ``list`` reflects
    the new label. Label is meta-only (the broker never sees it), so this
    path doesn't go through respawn.
    """
    fake = FakeEmail()
    await fake.start()
    sup = Supervisor(
        vault_dir=tmp_path / "vault",
        app_sock_path=tmp_path / "app.sock",
        sockets_dir=tmp_path / "sockets",
        host_paths=make_host_paths(tmp_path),
        catalog=_test_catalog(fake),
    )
    await sup.start()
    try:
        await _rpc_call(
            sup.app_sock_path,
            "add",
            {
                "slug": "icloud",
                "user_suffix": "personal",
                "label": "Original",
                "auth_blob": {"email": fake.user, "password": fake.password},
                "operation_grants": sorted(OPERATIONS_BY_GROUP["email"] | OPERATIONS_BY_GROUP["calendar"]),
            },
        )

        upd_resp = await _rpc_call(
            sup.app_sock_path,
            "update",
            {"id": "icloud_personal", "label": "Renamed"},
        )
        assert "error" not in upd_resp, upd_resp
        assert upd_resp["result"]["label"] == "Renamed"

        list_resp = await _rpc_call(sup.app_sock_path, "list", {})
        listed = next(
            i for i in list_resp["result"]["connections"]
            if i["id"] == "icloud_personal"
        )
        assert listed["label"] == "Renamed"
    finally:
        await sup.stop()
        await fake.stop()


@pytest.mark.asyncio
async def test_update_rejects_empty_body(tmp_path: Path) -> None:
    """``update {id}`` with no fields to change is BAD_REQUEST — caller has
    to specify at least one of operation_grants or label."""
    fake = FakeEmail()
    await fake.start()
    sup = Supervisor(
        vault_dir=tmp_path / "vault",
        app_sock_path=tmp_path / "app.sock",
        sockets_dir=tmp_path / "sockets",
        host_paths=make_host_paths(tmp_path),
        catalog=_test_catalog(fake),
    )
    await sup.start()
    try:
        await _rpc_call(
            sup.app_sock_path,
            "add",
            {
                "slug": "icloud",
                "user_suffix": "personal",
                "label": "iCloud",
                "auth_blob": {"email": fake.user, "password": fake.password},
                "operation_grants": sorted(OPERATIONS_BY_GROUP["email"] | OPERATIONS_BY_GROUP["calendar"]),
            },
        )

        resp = await _rpc_call(
            sup.app_sock_path, "update", {"id": "icloud_personal"},
        )
        assert resp["error"]["code"] == "BAD_REQUEST"
    finally:
        await sup.stop()
        await fake.stop()


@pytest.mark.asyncio
async def test_update_no_op_when_value_unchanged(tmp_path: Path) -> None:
    """Setting ``operation_grants`` to their current value doesn't restart the
    broker — the manager short-circuits and returns the existing record.
    No respawn means the broker PID is unchanged.
    """
    fake = FakeEmail()
    await fake.start()
    sup = Supervisor(
        vault_dir=tmp_path / "vault",
        app_sock_path=tmp_path / "app.sock",
        sockets_dir=tmp_path / "sockets",
        host_paths=make_host_paths(tmp_path),
        catalog=_test_catalog(fake),
    )
    await sup.start()
    try:
        await _rpc_call(
            sup.app_sock_path,
            "add",
            {
                "slug": "icloud",
                "user_suffix": "personal",
                "label": "iCloud test",
                "auth_blob": {"email": fake.user, "password": fake.password},
                "operation_grants": sorted(OPERATIONS_BY_GROUP["email"] - {"email.messages.send", "email.messages.move"}),
            },
        )
        old_pid = sup._registry.get("icloud_personal").broker.proc.pid

        upd_resp = await _rpc_call(
            sup.app_sock_path,
            "update",
            {"id": "icloud_personal", "operation_grants": sorted(OPERATIONS_BY_GROUP["email"] - {"email.messages.send", "email.messages.move"})},
        )
        assert "error" not in upd_resp, upd_resp
        assert sup._registry.get("icloud_personal").broker.proc.pid == old_pid
    finally:
        await sup.stop()
        await fake.stop()


@pytest.mark.asyncio
async def test_reconnect_keeps_broker_and_preserves_exact_grants(tmp_path: Path) -> None:
    fake = FakeEmail()
    await fake.start()
    sup = Supervisor(
        vault_dir=tmp_path / "vault",
        app_sock_path=tmp_path / "app.sock",
        sockets_dir=tmp_path / "sockets",
        host_paths=make_host_paths(tmp_path),
        catalog=_test_catalog(fake),
    )
    await sup.start()
    try:
        add_resp = await _rpc_call(
            sup.app_sock_path,
            "add",
            {
                "slug": "icloud",
                "user_suffix": "personal",
                "label": "iCloud test",
                "auth_blob": {"email": fake.user, "password": fake.password},
                "operation_grants": ["email.messages.search"],
            },
        )
        assert "error" not in add_resp, add_resp
        old_pid = sup._registry.get("icloud_personal").broker.proc.pid

        # Both IMAP and SMTP must authenticate using the replacement password.
        fake.password = "replacement-password"

        reconnect_resp = await _rpc_call(
            sup.app_sock_path,
            "reconnect",
            {
                "id": "icloud_personal",
                "auth_blob": {"email": fake.user, "password": fake.password},
            },
        )
        assert "error" not in reconnect_resp, reconnect_resp
        assert reconnect_resp["result"]["operation_grants"] == ["email.messages.search"]
        record = sup._registry.get("icloud_personal")
        assert record.broker.proc.pid == old_pid
        assert record.state == "running"
        response = await _rpc_call(record.broker.socket_path, "email.messages.search", {"folder": "INBOX", "query": "ALL"})
        assert "error" not in response, response
    finally:
        await sup.stop()
        await fake.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("reject_service", ["imap", "smtp"])
async def test_reconnect_bad_credentials_preserves_previous_connection(tmp_path: Path, reject_service: str) -> None:
    fake = FakeEmail()
    await fake.start()
    sup = Supervisor(
        vault_dir=tmp_path / "vault",
        app_sock_path=tmp_path / "app.sock",
        sockets_dir=tmp_path / "sockets",
        host_paths=make_host_paths(tmp_path),
        catalog=_test_catalog(fake),
    )
    await sup.start()
    try:
        add_resp = await _rpc_call(
            sup.app_sock_path,
            "add",
            {
                "slug": "icloud",
                "user_suffix": "personal",
                "label": "iCloud test",
                "auth_blob": {"email": fake.user, "password": fake.password},
                "operation_grants": ["email.mailboxes.list"],
            },
        )
        assert "error" not in add_resp, add_resp

        proc = sup._registry.get("icloud_personal").broker.proc
        if reject_service == "smtp":
            # IMAP accepts the candidate; SMTP rejection must clean it up too.
            fake.reject_next_n_smtp_auths = 1

        reconnect_resp = await _rpc_call(
            sup.app_sock_path,
            "reconnect",
            {
                "id": "icloud_personal",
                "auth_blob": {"email": fake.user, "password": "wrong" if reject_service == "imap" else fake.password},
            },
        )
        assert reconnect_resp["error"]["code"] == "AUTH"

        record = sup._registry.get("icloud_personal")
        assert record.broker.proc is proc
        assert record.state == "running"
        assert record.meta.agent_operation_grants == frozenset({"email.mailboxes.list"})
        mailboxes = await _rpc_call(record.broker.socket_path, "email.mailboxes.list", {})
        assert "error" not in mailboxes, mailboxes
    finally:
        await sup.stop()
        await fake.stop()


@pytest.mark.asyncio
async def test_grant_update_does_not_reauthenticate(tmp_path: Path) -> None:
    """A live grant edit does not depend on the upstream accepting a new login."""
    fake = FakeEmail()
    await fake.start()
    sup = Supervisor(
        vault_dir=tmp_path / "vault",
        app_sock_path=tmp_path / "app.sock",
        sockets_dir=tmp_path / "sockets",
        host_paths=make_host_paths(tmp_path),
        catalog=_test_catalog(fake),
    )
    await sup.start()
    try:
        add_resp = await _rpc_call(
            sup.app_sock_path,
            "add",
            {
                "slug": "icloud",
                "user_suffix": "personal",
                "label": "iCloud test",
                "auth_blob": {"email": fake.user, "password": fake.password},
                "operation_grants": ["email.mailboxes.list"],
            },
        )
        assert "error" not in add_resp, add_resp

        old_pid = sup._registry.get("icloud_personal").broker.proc.pid
        # Any accidental respawn would fail this update.
        fake.reject_next_n_imap_logins = 1
        update_resp = await _rpc_call(
            sup.app_sock_path,
            "update",
            {
                "id": "icloud_personal",
                "operation_grants": [
                    "email.mailboxes.list",
                    "email.messages.send",
                ],
            },
        )
        assert "error" not in update_resp, update_resp

        record = sup._registry.get("icloud_personal")
        assert record is not None
        assert record.state == "running"
        assert record.expected_termination is False
        assert record.broker.proc.pid == old_pid
        assert fake.reject_next_n_imap_logins == 1
        assert record.meta.agent_operation_grants == frozenset({"email.mailboxes.list", "email.messages.send"})
        raw = read_raw_meta(sup.vault_dir, "icloud_personal")
        assert raw["agent_operation_grants"] == ["email.mailboxes.list", "email.messages.send"]

        mailboxes = await _rpc_call(record.broker.socket_path, "email.mailboxes.list", {})
        assert "error" not in mailboxes, mailboxes
    finally:
        await sup.stop()
        await fake.stop()


@pytest.mark.asyncio
async def test_failed_reconnect_does_not_retry_old_credentials(tmp_path: Path) -> None:
    """A startup failure retains a brokerless record without a fallback spawn."""
    fake = FakeEmail()
    await fake.start()
    sup = Supervisor(
        vault_dir=tmp_path / "vault",
        app_sock_path=tmp_path / "app.sock",
        sockets_dir=tmp_path / "sockets",
        host_paths=make_host_paths(tmp_path),
        catalog=_test_catalog(fake),
    )
    await sup.start()
    try:
        added = await _rpc_call(
            sup.app_sock_path,
            "add",
            {
                "slug": "icloud",
                "user_suffix": "personal",
                "label": "iCloud test",
                "auth_blob": {"email": fake.user, "password": fake.password},
                "operation_grants": ["email.mailboxes.list"],
            },
        )
        assert "error" not in added, added

        # Degraded connections need a new process, unlike healthy live updates.
        record = sup._registry.get("icloud_personal")
        await sup._manager._stop_record_broker(record)
        record.state = "broken"
        # Leave one rejection unused to prove there was no fallback attempt.
        fake.reject_next_n_imap_logins = 2
        updated = await _rpc_call(
            sup.app_sock_path,
            "reconnect",
            {
                "id": "icloud_personal",
                "auth_blob": {"email": fake.user, "password": fake.password},
            },
        )
        assert updated["error"]["code"] == "AUTH"

        record = sup._registry.get("icloud_personal")
        assert record is not None
        assert record.state == "auth_failed"
        assert record.broker is None
        assert fake.reject_next_n_imap_logins == 1

        listed = await _rpc_call(sup.app_sock_path, "list", {})
        assert listed["result"]["connections"][0]["socket"] is None
    finally:
        await sup.stop()
        await fake.stop()


@pytest.mark.asyncio
async def test_model_provider_reconnect_keeps_process(tmp_path: Path) -> None:
    entry = ModelProviderCatalogEntry(
        slug="llm_openai",
        title="OpenAI",
        provider_protocol="openai",
        driver=BrokerDriver(
            id="test.llm_proxy",
            command=("python", "-m", "brokering.brokers.llm_proxy"),
            env_injection={"api_key": "LLM_API_KEY"},
        ),
        driver_config={
            "LLM_PROVIDER": "openai",
            "LLM_BASE_URL": "http://127.0.0.1:1",
        },
    )
    sup = Supervisor(
        vault_dir=tmp_path / "vault",
        app_sock_path=tmp_path / "app.sock",
        sockets_dir=tmp_path / "sockets",
        host_paths=make_host_paths(tmp_path),
        catalog={entry.slug: entry},
    )
    await sup.start()
    try:
        added = await _rpc_call(
            sup.app_sock_path,
            "add",
            {
                "slug": "llm_openai",
                "kind": "model_provider",
                "label": "OpenAI",
                "auth_blob": {"api_key": "old-key"},
            },
        )
        assert "error" not in added, added
        old_pid = sup._registry.get("llm_openai").broker.proc.pid

        reconnected = await _rpc_call(
            sup.app_sock_path,
            "reconnect",
            {
                "id": "llm_openai",
                "kind": "model_provider",
                "auth_blob": {"api_key": "new-key"},
            },
        )
        assert "error" not in reconnected, reconnected
        record = sup._registry.get("llm_openai")
        assert record.meta.kind == "model_provider"
        assert record.broker.proc.pid == old_pid
        assert record.state == "running"
    finally:
        await sup.stop()
