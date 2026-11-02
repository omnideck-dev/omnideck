"""Vault migration 001: replace v1/v2 permissions with explicit v3 grants.

Only .meta files are read or rewritten. No key, token bundle, catalog, or
network access is needed. Keep these historical mappings frozen: later tool
additions must never expand an old user's permission selection.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from brokering.supervisor._store import _atomic_write, backup_meta_before_v3

_LEGACY_READ: dict[str, frozenset[str]] = {
    "email": frozenset(
        {
            "email.mailboxes.list",
            "email.messages.list",
            "email.messages.search",
            "email.messages.get",
            "email.attachments.download",
        }
    ),
    "calendar": frozenset(
        {
            "calendar.calendars.list",
            "calendar.events.list",
            "calendar.events.search",
        }
    ),
    "drive": frozenset(
        {
            "drive.files.list",
            "drive.files.search",
            "drive.files.get_metadata",
            "drive.files.export",
        }
    ),
    "contacts": frozenset({"contacts.people.list", "contacts.people.search"}),
    # A generic request cannot honestly be represented as read-only.  Legacy
    # http:r therefore migrates to no grant instead of widening authority.
    "http": frozenset(),
}

_LEGACY_WRITE: dict[str, frozenset[str]] = {
    "email": frozenset({"email.messages.move", "email.messages.send"}),
    "calendar": frozenset(
        {
            "calendar.events.create",
            "calendar.events.update",
            "calendar.events.delete",
            "calendar.series.update",
            "calendar.series.delete",
        }
    ),
    "drive": frozenset(
        {
            "drive.files.upload",
            "drive.folders.create",
            "drive.files.update",
            "drive.files.trash",
            "drive.files.share",
        }
    ),
    "contacts": frozenset(),
    "http": frozenset({"http.request"}),
}


_SLUG_GROUPS = {
    "icloud": ("email", "calendar"),
    "gmail": ("email",),
    "google_workspace": ("email", "calendar", "drive", "contacts"),
    "http": ("http",),
}
_MODEL_SLUGS = frozenset({
    "llm_openai", "llm_anthropic", "llm_openrouter", "llm_openai_compat",
})


def convert_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert historical metadata without consulting current OAuth scopes."""
    version = raw.get("version", 1)
    if type(version) is not int or version not in {1, 2, 3}:
        raise ValueError("unsupported connection metadata version")
    if version == 3:
        return dict(raw)

    slug = raw.get("slug")
    if not isinstance(slug, str) or slug not in {*_SLUG_GROUPS, *_MODEL_SLUGS}:
        raise ValueError("unknown legacy connection preset")
    # Only historical metadata fields can enter the plaintext output. Auth
    # bundles belong exclusively to .enc and are never accepted here.
    allowed = {"version", "id", "slug", "label", "added_at", "updated_at",
               "permissions", "write_allowed", "kind", "agent_operation_grants"}
    if raw.keys() - allowed:
        raise ValueError("unexpected legacy metadata fields")
    for field in ("id", "label", "added_at", "updated_at"):
        if not isinstance(raw.get(field), str) or not raw[field]:
            raise ValueError("missing or invalid legacy metadata field")
    for field in ("added_at", "updated_at"):
        datetime.fromisoformat(raw[field])
    result = dict(raw)
    result["version"] = 3
    result["kind"] = "model_provider" if slug in _MODEL_SLUGS else "integration"
    permissions = result.pop("permissions", {})
    write_allowed = result.pop("write_allowed", False)
    result.pop("agent_operation_grants", None)
    if slug in _MODEL_SLUGS:
        return result
    if version == 1:
        if type(write_allowed) is not bool:
            raise ValueError("invalid legacy write flag")
        permissions = {group: "rw" if write_allowed else "r" for group in _SLUG_GROUPS[slug]}
    if not isinstance(permissions, dict):
        raise ValueError("invalid legacy permissions")
    if any(not isinstance(key, str) or value not in ("off", "r", "rw")
           for key, value in permissions.items()):
        raise ValueError("invalid legacy permission entry")
    grants: set[str] = set()
    for group in _SLUG_GROUPS[slug]:
        access = permissions.get(group, "off")
        if access in ("r", "rw"):
            grants.update(_LEGACY_READ[group])
        if access == "rw":
            grants.update(_LEGACY_WRITE[group])
    result["agent_operation_grants"] = sorted(grants)
    return result


def migrate(vault_dir: Path) -> None:
    """Back up and atomically upgrade metadata, including orphan .meta files."""
    for path in sorted((vault_dir / "creds").glob("*.meta")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("id") != path.stem:
                raise ValueError("invalid connection metadata identity")
            converted = convert_metadata(raw)
            if raw.get("version") == 3:
                continue
            data = json.dumps(converted, sort_keys=True).encode("utf-8")
        except (ValueError, TypeError):
            # Do not include file contents or validation inputs in logs/errors.
            raise ValueError(f"Cannot migrate connection metadata {path.name}") from None
        # Preserve the first backup across retries and the previous in-place
        # migration's backups. Never overwrite an original with converted data.
        backup_meta_before_v3(vault_dir, path.stem)
        _atomic_write(path, data)
