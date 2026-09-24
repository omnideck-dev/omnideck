"""Folder registry — user-created groups for organizing conversations.

Folders are pure metadata: the registry here stores the folder definitions
(id, name, icon, order) in a single JSON file under the conversations root,
and each conversation records which folder it belongs to via a ``folder_id``
in its own metadata.json. Nothing about a conversation moves on disk when it
is filed into a folder.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from config import load_config

from ._models import Folder

logger = logging.getLogger(__name__)

# The registry file sits beside the per-conversation directories. It's a plain
# file, so the directory-based conversation scan never mistakes it for a chat.
_FOLDERS_FILENAME = "_folders.json"

# The sidebar caps folder names at this length; the store enforces the same
# bound so a crafted request can't persist an oversized name.
_MAX_NAME_LEN = 40

# A fresh folder starts with a plain folder glyph; the user can pick another
# icon from the sidebar afterwards.
_DEFAULT_ICON = "bi-folder"


def _folders_path() -> Path:
    cfg = load_config()
    return Path(cfg.settings.home_dir) / "conversations" / _FOLDERS_FILENAME


def _read_raw() -> list[dict]:
    path = _folders_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to read folders registry")
        return []
    return data if isinstance(data, list) else []


def _write_raw(folders: list[dict]) -> None:
    path = _folders_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(folders, indent=2), encoding="utf-8")
    tmp.replace(path)


def list_folders() -> list[Folder]:
    """Return all folders, ordered for display (by ``order`` then creation)."""
    folders = [Folder(**f) for f in _read_raw() if isinstance(f, dict) and f.get("id")]
    folders.sort(key=lambda f: (f.order, f.created_at))
    return folders


def folder_exists(folder_id: str) -> bool:
    """Report whether a folder with this id is registered."""
    return any(f.get("id") == folder_id for f in _read_raw())


def create_folder(name: str, icon: str | None = None) -> Folder:
    """Create a folder with the given name, icon, and sort order."""
    raw = _read_raw()
    order = 1 + max((int(f.get("order", 0)) for f in raw), default=0)
    folder = Folder(
        id=uuid.uuid4().hex[:12],
        name=name.strip()[:_MAX_NAME_LEN],
        icon=icon or _DEFAULT_ICON,
        order=order,
        created_at=datetime.now(UTC).isoformat(),
    )
    raw.append(folder.model_dump())
    _write_raw(raw)
    return folder


def update_folder(
    folder_id: str,
    *,
    name: str | None = None,
    icon: str | None = None,
    order: int | None = None,
) -> Folder | None:
    """Update a folder's name, icon, and/or order. Returns None if missing."""
    raw = _read_raw()
    updated: Folder | None = None
    for entry in raw:
        if entry.get("id") != folder_id:
            continue
        if name is not None:
            entry["name"] = name.strip()[:_MAX_NAME_LEN]
        if icon is not None:
            entry["icon"] = icon
        if order is not None:
            entry["order"] = order
        updated = Folder(**entry)
        break
    if updated is not None:
        _write_raw(raw)
    return updated


def delete_folder(folder_id: str) -> bool:
    """Remove a folder from the registry. Returns False if it didn't exist.

    This only deletes the folder definition. Clearing the ``folder_id`` from
    the conversations that referenced it is left to the caller, which keeps
    this registry independent of the conversation store; once cleared, those
    chats fall back to the normal date-grouped listing.
    """
    raw = _read_raw()
    remaining = [f for f in raw if f.get("id") != folder_id]
    if len(remaining) == len(raw):
        return False
    _write_raw(remaining)
    return True
