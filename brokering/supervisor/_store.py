"""Atomic I/O for integration ``.meta`` (plaintext) and ``.enc`` (ciphertext) files.

Every write goes through ``tmp + fsync + rename`` so readers always see a
coherent file. Non-secret metadata is plaintext JSON; only the credential
bundle is encrypted. This split is what lets the ``list`` and permission-toggle
paths avoid loading the master key at all — handy because the key is the
expensive thing to touch, both for process lifecycle and for access control.

Vault layout::

    <vault_dir>/
        .master-key
        creds/
            <connection_id>.meta    plaintext JSON
            <connection_id>.enc     AES-256-GCM encrypted secret bundle
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from pathlib import Path

from brokering._perms import VAULT_FILE_MODE
from brokering.connection_data import BrokerConnectionData
from brokering.supervisor._crypto import DecryptError, decrypt_secrets, encrypt_secrets
from brokering.supervisor.types import ConnectionMeta

logger = logging.getLogger(__name__)


def creds_dir(vault_dir: Path) -> Path:
    """Path to the per-integration creds directory."""
    return vault_dir / "creds"


def meta_path(vault_dir: Path, connection_id: str) -> Path:
    """Path to ``<id>.meta`` inside the creds dir."""
    return creds_dir(vault_dir) / f"{connection_id}.meta"


def meta_backup_path(vault_dir: Path, connection_id: str) -> Path:
    """One-time backup retained when legacy metadata is migrated to v3."""
    return creds_dir(vault_dir) / f"{connection_id}.meta.pre-v3.bak"


def enc_path(vault_dir: Path, connection_id: str) -> Path:
    """Path to ``<id>.enc`` inside the creds dir."""
    return creds_dir(vault_dir) / f"{connection_id}.enc"


def _atomic_write(path: Path, data: bytes, *, mode: int = VAULT_FILE_MODE) -> None:
    """Write ``data`` to ``path`` atomically, then apply ``mode``.

    Default ``mode`` is :data:`brokering._perms.VAULT_FILE_MODE`
    (``0o600``) — both ``.meta`` and ``.enc`` are owner-only.

    Writes to a ``.tmp`` sibling, fsyncs, chmods, then renames. ``rename``
    inside a single filesystem is atomic, so readers never observe a
    partially-written file — they see either the old one or the new one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    tmp.chmod(mode)
    tmp.rename(path)


def write_meta(vault_dir: Path, meta: ConnectionMeta) -> None:
    """Atomically write the ``.meta`` file for ``meta.id``."""
    data = meta.model_dump_json().encode("utf-8")
    _atomic_write(meta_path(vault_dir, meta.id), data)


def backup_meta_before_v3(vault_dir: Path, connection_id: str) -> Path:
    """Persist the original metadata once before an in-place v3 migration."""
    backup = meta_backup_path(vault_dir, connection_id)
    if not backup.exists():
        _atomic_write(backup, meta_path(vault_dir, connection_id).read_bytes())
    return backup


def read_raw_meta(vault_dir: Path, connection_id: str) -> dict:
    """Load the ``.meta`` file as a raw dict.

    Callers are responsible for version migration and validation.
    """
    path = meta_path(vault_dir, connection_id)
    return json.loads(path.read_text(encoding="utf-8"))


def write_secrets(
    vault_dir: Path,
    connection_id: str,
    master_key: bytes,
    secret_bundle: Mapping[str, str],
) -> None:
    """Encrypt ``secret_bundle`` and atomically write the ``.enc`` file."""
    blob = encrypt_secrets(master_key, connection_id, dict(secret_bundle))
    _atomic_write(enc_path(vault_dir, connection_id), blob)


def read_secrets(
    vault_dir: Path,
    connection_id: str,
    master_key: bytes,
) -> BrokerConnectionData:
    """Decrypt the ``.enc`` file. Raises :class:`supervisor._crypto.DecryptError`
    on any tamper or AAD mismatch."""
    blob = enc_path(vault_dir, connection_id).read_bytes()
    try:
        return BrokerConnectionData.from_wire(decrypt_secrets(master_key, connection_id, blob))
    except ValueError as exc:
        raise DecryptError("stored authentication data is invalid") from exc


def delete_connection(vault_dir: Path, connection_id: str) -> None:
    """Remove both ``.meta`` and ``.enc`` files for an integration.

    Idempotent — missing files are silently skipped so callers can safely call
    remove more than once without racing on partial state.
    """
    meta_path(vault_dir, connection_id).unlink(missing_ok=True)
    enc_path(vault_dir, connection_id).unlink(missing_ok=True)
    meta_backup_path(vault_dir, connection_id).unlink(missing_ok=True)


def list_connection_ids(vault_dir: Path) -> list[str]:
    """Return the integration IDs that have BOTH a ``.meta`` and a ``.enc`` on disk.

    Orphans (one side missing) are silently omitted — they represent a
    partial-write crash and the pair is unusable anyway. The caller can decide
    whether to log a warning.
    """
    cdir = creds_dir(vault_dir)
    if not cdir.exists():
        return []
    meta_ids = {p.stem for p in cdir.glob("*.meta")}
    enc_ids = {p.stem for p in cdir.glob("*.enc")}
    return sorted(meta_ids & enc_ids)
