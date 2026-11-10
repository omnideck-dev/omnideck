"""Tests for supervisor/_store.py — atomic .meta + .enc I/O."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from brokering.connection_data import BrokerConnectionData
from brokering.supervisor._crypto import DecryptError, load_or_init_master_key
from brokering.supervisor._store import (
    backup_meta_before_v3,
    delete_connection,
    enc_path,
    list_connection_ids,
    meta_path,
    meta_backup_path,
    read_raw_meta,
    read_secrets,
    write_meta,
    write_secrets,
)
from brokering.supervisor.types import IntegrationConnectionMeta


def _meta(id_: str = "icloud_personal") -> IntegrationConnectionMeta:
    now = datetime.now(UTC)
    return IntegrationConnectionMeta(
        id=id_,
        slug="icloud",
        label="iCloud test",
        added_at=now,
        updated_at=now,
    )


def test_meta_round_trip(tmp_path: Path) -> None:
    """write_meta then read_raw_meta + validate returns an equivalent model."""
    meta = _meta()

    write_meta(tmp_path, meta)
    raw = read_raw_meta(tmp_path, meta.id)
    loaded = IntegrationConnectionMeta.model_validate(raw)

    assert loaded == meta


def test_meta_file_mode_is_0600(tmp_path: Path) -> None:
    """Even though .meta is plaintext, we don't expose it to other users."""
    meta = _meta()
    write_meta(tmp_path, meta)

    mode = meta_path(tmp_path, meta.id).stat().st_mode & 0o777
    assert mode == 0o600


def test_secrets_round_trip(tmp_path: Path) -> None:
    """write_secrets then read_secrets reproduces the original dict."""
    key = load_or_init_master_key(tmp_path)
    bundle = {"email": "you@icloud.com", "password": "xxxx-xxxx-xxxx-xxxx"}

    write_secrets(tmp_path, "icloud_personal", key, bundle)
    back = read_secrets(tmp_path, "icloud_personal", key)

    assert back == bundle
    assert isinstance(back, BrokerConnectionData)


def test_invalid_stored_authentication_fails_as_decryption_error(tmp_path: Path) -> None:
    key = load_or_init_master_key(tmp_path)
    write_secrets(tmp_path, "invalid", key, {"token": None})
    with pytest.raises(DecryptError, match="stored authentication data is invalid"):
        read_secrets(tmp_path, "invalid", key)


def test_legacy_scope_array_restores_as_typed_authentication(tmp_path: Path) -> None:
    key = load_or_init_master_key(tmp_path)
    write_secrets(tmp_path, "legacy", key, {"scopes": ["scope-a", "scope-b"]})
    restored = read_secrets(tmp_path, "legacy", key)
    assert restored.granted_scopes == frozenset({"scope-a", "scope-b"})
    assert restored["scopes"] == "scope-a scope-b"


def test_write_is_atomic_no_tmp_left_behind(tmp_path: Path) -> None:
    """Successful writes leave no stray ``.tmp`` files in the creds dir."""
    meta = _meta()

    write_meta(tmp_path, meta)

    tmps = list((tmp_path / "creds").glob("*.tmp"))
    assert tmps == []


def test_pre_v3_backup_is_one_time_and_preserves_original_bytes(tmp_path: Path) -> None:
    meta = _meta()
    write_meta(tmp_path, meta)
    original = meta_path(tmp_path, meta.id).read_bytes()
    backup_meta_before_v3(tmp_path, meta.id)

    changed = meta.model_copy(update={"label": "Changed"})
    write_meta(tmp_path, changed)
    backup_meta_before_v3(tmp_path, meta.id)

    assert meta_backup_path(tmp_path, meta.id).read_bytes() == original


def test_delete_removes_both_files(tmp_path: Path) -> None:
    """delete_connection unlinks .meta and .enc together."""
    key = load_or_init_master_key(tmp_path)
    meta = _meta()
    write_meta(tmp_path, meta)
    backup_meta_before_v3(tmp_path, meta.id)
    write_secrets(tmp_path, meta.id, key, {"password": "x"})

    delete_connection(tmp_path, meta.id)

    assert not meta_path(tmp_path, meta.id).exists()
    assert not enc_path(tmp_path, meta.id).exists()
    assert not meta_backup_path(tmp_path, meta.id).exists()


def test_delete_is_idempotent(tmp_path: Path) -> None:
    """Calling delete twice (or on a never-existed id) doesn't raise."""
    delete_connection(tmp_path, "never_existed")
    delete_connection(tmp_path, "never_existed")  # no error either time


def test_list_only_returns_paired_ids(tmp_path: Path) -> None:
    """Orphan .meta-without-.enc or .enc-without-.meta entries are skipped."""
    key = load_or_init_master_key(tmp_path)

    # Properly paired integration.
    paired = _meta("paired_id")
    write_meta(tmp_path, paired)
    write_secrets(tmp_path, paired.id, key, {"v": 1})

    # Orphan .meta (no .enc).
    orphan_meta = _meta("orphan_meta_id")
    write_meta(tmp_path, orphan_meta)

    # Orphan .enc (no .meta).
    write_secrets(tmp_path, "orphan_enc_id", key, {"v": 2})

    ids = list_connection_ids(tmp_path)
    assert ids == ["paired_id"]


def test_list_returns_empty_when_creds_dir_missing(tmp_path: Path) -> None:
    """Before any add, the vault has no creds dir yet. list returns []."""
    assert list_connection_ids(tmp_path) == []
