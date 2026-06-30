"""Persistence layer for conversation data.

All conversation data is stored under per-conversation subdirectories::

    {home_dir}/conversations/{conv_id}/
        events.jsonl      # append-only event log (source of truth)
        metadata.json     # title, preview state, loaded skills
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config import load_config

from ._models import ConversationSummary

logger = logging.getLogger(__name__)


def _get_conversations_dir() -> Path:
    cfg = load_config()
    return Path(cfg.settings.home_dir) / "conversations"


def _get_conv_dir(conversation_id: str) -> Path:
    return _get_conversations_dir() / conversation_id


# -- Conversation metadata persistence ---------------------------------------


def save_loaded_skills(conversation_id: str, skills: frozenset[str]) -> None:
    """Persist loaded skill names to conversation metadata."""
    conv_dir = _get_conv_dir(conversation_id)
    conv_dir.mkdir(parents=True, exist_ok=True)

    metadata_path = conv_dir / "metadata.json"
    metadata: dict[str, Any] = {}
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    metadata["loaded_skills"] = sorted(skills)
    tmp = metadata_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    tmp.replace(metadata_path)


def load_loaded_skills(conversation_id: str) -> set[str]:
    """Load persisted skill names from conversation metadata."""
    metadata = load_conversation_metadata(conversation_id)
    raw = metadata.get("loaded_skills", [])
    return set(raw) if isinstance(raw, list) else set()


def save_conversation_title(conversation_id: str, title: str) -> None:
    """Save or update the title for a conversation."""
    conv_dir = _get_conv_dir(conversation_id)
    conv_dir.mkdir(parents=True, exist_ok=True)

    metadata_path = conv_dir / "metadata.json"
    metadata: dict[str, Any] = {"title": title}
    if metadata_path.exists():
        try:
            existing = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata = {**existing, "title": title}
        except Exception:
            pass

    tmp = metadata_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    tmp.replace(metadata_path)


def save_conversation_pinned(conversation_id: str, pinned: bool) -> None:
    """Save or update the pinned flag for a conversation.

    Pinned conversations float to a dedicated section at the top of the
    sidebar. The flag lives in metadata.json alongside the title.
    """
    conv_dir = _get_conv_dir(conversation_id)
    conv_dir.mkdir(parents=True, exist_ok=True)

    metadata_path = conv_dir / "metadata.json"
    metadata: dict[str, Any] = {}
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    metadata["pinned"] = pinned
    tmp = metadata_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    tmp.replace(metadata_path)


def save_conversation_profile(conversation_id: str, profile_id: str) -> None:
    """Save the agent profile selected for a conversation.

    Each conversation locks in its own agent profile so returning to it
    later restores the same behavioral configuration. The id lives in
    metadata.json alongside the title and pinned flag.
    """
    conv_dir = _get_conv_dir(conversation_id)
    conv_dir.mkdir(parents=True, exist_ok=True)

    metadata_path = conv_dir / "metadata.json"
    metadata: dict[str, Any] = {}
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    metadata["profile_id"] = profile_id
    tmp = metadata_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    tmp.replace(metadata_path)


def load_conversation_profile(conversation_id: str) -> str | None:
    """Load the agent profile id saved for a conversation, or None."""
    metadata = load_conversation_metadata(conversation_id)
    profile_id = metadata.get("profile_id")
    return profile_id if isinstance(profile_id, str) else None


def load_conversation_metadata(conversation_id: str) -> dict[str, Any]:
    """Load conversation metadata including title.

    Returns an empty dict if no metadata exists for the conversation.
    """
    path = _get_conv_dir(conversation_id) / "metadata.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_preview_state(conversation_id: str, state: dict[str, Any]) -> None:
    """Persist the user's preview-panel tab state for a conversation."""
    conv_dir = _get_conv_dir(conversation_id)
    conv_dir.mkdir(parents=True, exist_ok=True)

    metadata_path = conv_dir / "metadata.json"
    metadata: dict[str, Any] = {}
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    metadata["preview_state"] = state
    tmp = metadata_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    tmp.replace(metadata_path)


def load_preview_state(conversation_id: str) -> dict[str, Any]:
    """Load the persisted preview-panel state, or empty dict if none."""
    metadata = load_conversation_metadata(conversation_id)
    state = metadata.get("preview_state")
    return state if isinstance(state, dict) else {}


def mark_file_focused(conversation_id: str, path: str) -> dict[str, Any]:
    """Mark a file as the open, active tab in a conversation's preview state.

    Merges into any existing state: adds ``path`` to ``open_files`` if absent
    and sets ``active_tab`` to ``file:<path>``, leaving the other panel flags
    untouched. Pre-focusing a file this way lets the normal resume path restore
    it as the active tab when the conversation is reopened. Returns the merged
    state.
    """
    state = load_preview_state(conversation_id)
    open_files = state.get("open_files")
    if not isinstance(open_files, list):
        open_files = []
    if path not in open_files:
        open_files.append(path)
    state["open_files"] = open_files
    state["active_tab"] = f"file:{path}"
    save_preview_state(conversation_id, state)
    return state


# -- Conversation listing and deletion -----------------------------------------

def list_conversations() -> list[ConversationSummary]:
    """List all conversations by scanning subdirectories.

    A conversation is recognised by the presence of ``events.jsonl``.
    The first user message and turn count are derived from the event
    log; the title comes from ``metadata.json`` if present.
    """
    conv_root = _get_conversations_dir()
    if not conv_root.exists():
        return []

    summaries: list[ConversationSummary] = []
    for entry in conv_root.iterdir():
        if not entry.is_dir():
            continue
        events_path = entry / "events.jsonl"
        if not events_path.exists():
            continue
        try:
            first_msg = ""
            turn_count = 0
            first_event_ts = ""
            with events_path.open(encoding="utf-8") as f:
                for raw in f:
                    if not raw.strip():
                        continue
                    e = json.loads(raw)
                    if not first_event_ts:
                        first_event_ts = e.get("timestamp", "") or ""
                    # Count user messages only on the root agent so
                    # nudges to sub-agents don't inflate the turn
                    # count. Root agent ids look like ``root.<profile>.<n>``;
                    # sub-agents append further segments, so the depth
                    # is the number of dots minus two.
                    if e.get("type") == "user_message" and (
                        e.get("agent_id") or ""
                    ).count(".") == 2:
                        turn_count += 1
                        if not first_msg:
                            first_msg = e.get("content", "") or ""
            if len(first_msg) > 200:
                first_msg = first_msg[:200] + "..."
            # started_at = timestamp of the first event in the log. mtime
            # would shift forward every time we append a new event, putting
            # every active conversation into the "Today" bucket.
            started_at = first_event_ts or datetime.fromtimestamp(
                events_path.stat().st_mtime, tz=UTC,
            ).isoformat()

            # Load title + pinned flag from metadata (if available)
            metadata = load_conversation_metadata(entry.name)
            title = metadata.get("title", "")
            pinned = bool(metadata.get("pinned", False))

            summaries.append(ConversationSummary(
                conversation_id=entry.name,
                first_message=first_msg,
                title=title,
                started_at=started_at,
                turn_count=turn_count,
                pinned=pinned,
            ))
        except Exception:
            logger.exception("Failed to read conversation %s", entry.name)

    summaries.sort(key=lambda s: s.started_at, reverse=True)
    return summaries


def conversation_exists(conversation_id: str) -> bool:
    """Report whether a conversation has a persisted event log on disk."""
    return (_get_conv_dir(conversation_id) / "events.jsonl").exists()


def delete_conversation(conversation_id: str) -> bool:
    """Delete a conversation and all its data."""
    conv_dir = _get_conv_dir(conversation_id)
    if not conv_dir.exists():
        return False
    shutil.rmtree(conv_dir)
    # Remove empty parent directories up to the conversations root.
    conv_root = _get_conversations_dir()
    parent = conv_dir.parent
    while parent != conv_root and parent.is_dir():
        try:
            parent.rmdir()  # only succeeds if empty
            parent = parent.parent
        except OSError:
            break
    return True
