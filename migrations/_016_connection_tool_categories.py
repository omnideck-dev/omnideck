"""Freeze legacy integration categories to existing connection identities once."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path


NAME = "016_connection_tool_categories"
CLEANUP_NAME = "016_connection_tool_categories_cleanup"
LEGACY = frozenset({"email", "calendar", "drive", "contacts", "http", "mcp"})


def _atomic_json(path: Path, value: object) -> None:
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".categories-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _rewrite_records(directory: Path, name: str, transform: Callable[[list[str]], list[str]]) -> None:
    for subdir in ("skills", "agent_profiles"):
        for path in sorted((directory / subdir).glob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            original = record.get("tool_categories", [])
            updated = transform(original)
            if updated == original and "tool_categories" in record:
                continue
            backup = directory / "migration-backups" / name / subdir / path.name
            backup.parent.mkdir(parents=True, exist_ok=True)
            if not backup.exists():
                shutil.copy2(path, backup)
            record["tool_categories"] = updated
            _atomic_json(path, record)


def _connection_mapping(vault_dir: Path) -> dict[str, list[str]]:
    """Read saved approvals only; no broker process, API, key or ciphertext I/O."""
    mapping: dict[str, list[str]] = {category: [] for category in LEGACY}
    for path in sorted((vault_dir / "creds").glob("*.meta")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("version") != 3 or record.get("id") != path.stem:
            raise ValueError(f"Invalid connection metadata: {path.name}")
        kind = record.get("kind")
        if kind == "model_provider":
            continue
        grants = record.get("agent_operation_grants")
        if kind != "integration" or not isinstance(grants, list) or any(not isinstance(op, str) for op in grants):
            raise ValueError(f"Invalid connection approvals: {path.name}")
        # Match the supervisor's inventory: orphan metadata is not a connection.
        # Only check the credential file's existence; never read its contents.
        if not path.with_suffix(".enc").is_file():
            continue
        for category in LEGACY:
            if any(op.startswith(f"{category}.") for op in grants):
                mapping[category].append(f"integration:{record['id']}")
    return mapping


def migrate_connections(state_dir: Path, *, vault_dir: Path) -> None:
    """Convert saved selections after vault metadata migration, before services.

    A checkpoint freezes the original mapping across crashes. Category selections
    intentionally broaden to all approved operations of each mapped connection.
    No later/new connection can enter the mapping. Original records are backed up.
    """
    checkpoint = state_dir / ".connection-category-mapping.json"
    if checkpoint.exists():
        mapping = json.loads(checkpoint.read_text(encoding="utf-8"))
    else:
        mapping = _connection_mapping(vault_dir)
        _atomic_json(checkpoint, mapping)

    _rewrite_records(state_dir, NAME, lambda original: list(dict.fromkeys(
        item for category in original
        for item in mapping.get(category, [] if category in LEGACY else [category])
    )))


def cleanup(state_dir: Path) -> None:
    """Remove obsolete broad IDs from migrated previews; never remap connections."""
    _rewrite_records(state_dir, CLEANUP_NAME, lambda original: [cid for cid in original if cid not in LEGACY])
