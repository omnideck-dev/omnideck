"""Vault migrations operate on metadata only and can resume interrupted upgrades."""

import json
from datetime import UTC, datetime

import pytest

from brokering.migrations import run_vault_migrations
from brokering.migrations import _001_operation_grants as migration
from brokering.supervisor._crypto import load_or_init_master_key
from brokering.supervisor._store import (
    enc_path, meta_backup_path, meta_path, write_secrets,
)


def _stage(vault, iid="gmail_example", **overrides):
    now = datetime.now(UTC).isoformat()
    raw = {
        "version": 2, "id": iid, "slug": "gmail", "label": "Example",
        "added_at": now, "updated_at": now, "permissions": {"email": "r"},
    } | overrides
    path = meta_path(vault, iid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_migration_preserves_ciphertext_and_writes_no_secrets(tmp_path, monkeypatch, caplog):
    vault = tmp_path / "vault"
    path = _stage(vault)
    original = path.read_bytes()
    key = load_or_init_master_key(vault)
    secret = "sentinel-do-not-write-plaintext"
    write_secrets(vault, "gmail_example", key, {"password": secret})
    encrypted = enc_path(vault, "gmail_example").read_bytes()

    def forbid_decryption(*args, **kwargs):
        raise AssertionError("Migration must not decrypt credentials")

    monkeypatch.setattr("brokering.supervisor._crypto.decrypt_secrets", forbid_decryption)
    monkeypatch.setattr("brokering.supervisor._store.decrypt_secrets", forbid_decryption)
    run_vault_migrations(vault)
    assert enc_path(vault, "gmail_example").read_bytes() == encrypted
    assert (vault / ".master-key").read_bytes() == key
    assert meta_backup_path(vault, "gmail_example").read_bytes() == original
    ledger = vault / ".migrations.json"
    assert json.loads(ledger.read_text()) == ["001_operation_grants"]
    assert not (tmp_path / ".migrations.json").exists()
    for file in vault.rglob("*"):
        if file.is_file():
            assert secret.encode() not in file.read_bytes()
    for file in (path, ledger, meta_backup_path(vault, "gmail_example")):
        assert file.stat().st_mode & 0o777 == 0o600
    assert secret not in caplog.text
    assert not list(vault.rglob("*.tmp"))


def test_partial_failure_retries_without_replacing_original_backups(tmp_path, monkeypatch):
    first = _stage(tmp_path, "a")
    second = _stage(tmp_path, "b")
    originals = {p.stem: p.read_bytes() for p in (first, second)}
    write = migration._atomic_write

    def fail_second(path, data):
        if path == second:
            raise OSError("simulated write failure")
        write(path, data)

    monkeypatch.setattr(migration, "_atomic_write", fail_second)
    with pytest.raises(OSError, match="simulated"):
        run_vault_migrations(tmp_path)
    assert json.loads(first.read_text())["version"] == 3
    assert json.loads(second.read_text())["version"] == 2
    assert not (tmp_path / ".migrations.json").exists()
    monkeypatch.setattr(migration, "_atomic_write", write)
    run_vault_migrations(tmp_path)
    snapshot = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    run_vault_migrations(tmp_path)
    assert snapshot == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    for iid, original in originals.items():
        assert meta_backup_path(tmp_path, iid).read_bytes() == original


@pytest.mark.parametrize("overrides", [
    {"version": 99}, {"slug": "unknown"}, {"permissions": {"email": "invalid"}},
    {"password": "must-not-be-copied"},
])
def test_invalid_metadata_is_not_backed_up_or_marked_complete(tmp_path, overrides):
    path = _stage(tmp_path, **overrides)
    original = path.read_bytes()
    with pytest.raises(ValueError, match="Cannot migrate connection metadata"):
        run_vault_migrations(tmp_path)
    assert path.read_bytes() == original
    assert not meta_backup_path(tmp_path, "gmail_example").exists()
    assert not (tmp_path / ".migrations.json").exists()
