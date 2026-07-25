"""Append-only events.jsonl writer for a conversation.

One JSON line per event, in publish order. Each line is a flat dict with
envelope fields (id, type, timestamp, conversation_id, agent_id,
agent_name, depth) merged with the payload's own fields.

Designed to subscribe to a ConversationHistory: pass ``handle_event`` as
the observer callback. Open-append-close per line keeps the layer simple
at the cost of an fsync per event. Acceptable while traffic is
single-process and human-paced; revisit if events.jsonl ever becomes a
hot path.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sdk.events._models import AgentEvent

from ._store import _get_conv_dir

logger = logging.getLogger(__name__)

# Types persisted to events.jsonl. Excludes purely transient dispatcher
# events: streaming ``content`` deltas (rolled up into ``iteration``),
# the legacy ``tool_call`` notification (carried inside ``iteration``),
# turn boundary signals, and UI-only previews (generation_preview,
# audio_playback, desktop_active). Panel state is also excluded — the UI
# shows only the latest snapshot per browser tab and the last N terminal
# commands, so those live in bounded overwrite-in-place sidecars
# (browser_tabs.json, terminal.json) instead of growing the append-only
# log forever (real logs were >90% screenshots before the split).
_PERSISTED_TYPES: frozenset[str] = frozenset({
    "user_message",
    "iteration",
    "tool_result",
    "compaction",
    "agent_started",
    "agent_completed",
    "spawn_requested",
    "file_output",
    "tool_created",
    "context_usage",
    "error",
})


def _serialize_event(event: AgentEvent, conversation_id: str) -> dict[str, Any]:
    """Render an AgentEvent as the flat dict shape persisted on disk."""
    return event.to_flat_dict(conversation_id)


class EventsLogWriter:
    """Subscribes to a dispatcher and appends each event to events.jsonl.

    The file is created lazily on the first event. The directory is
    created if needed.
    """

    def __init__(self, conversation_id: str) -> None:
        self._conversation_id = conversation_id
        self._path: Path = _get_conv_dir(conversation_id) / "events.jsonl"
        self._ensured = False

    def _ensure_dir(self) -> None:
        if self._ensured:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._ensured = True

    def handle_event(self, event: AgentEvent) -> None:
        """Append a single event line to events.jsonl. Logs but never raises."""
        if event.payload.type not in _PERSISTED_TYPES:
            return
        try:
            self._ensure_dir()
            flat = _serialize_event(event, self._conversation_id)
            line = json.dumps(flat, default=str)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.write("\n")
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "Failed to append event to %s (event_id=%s, type=%s)",
                self._path, event.id, event.payload.type,
            )


def load_events_jsonl(conversation_id: str) -> list[dict[str, Any]]:
    """Read events.jsonl for a conversation, return an empty list if missing.

    Each line is parsed as a flat event dict (the same shape produced
    by EventsLogWriter / build_llm_view). Malformed lines are
    skipped with a logged warning so a single corrupted record can't
    break resume.
    """
    path = _get_conv_dir(conversation_id) / "events.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not raw.strip():
            continue
        try:
            rows.append(json.loads(raw))
        except Exception:
            logger.exception(
                "Skipping malformed events.jsonl line %d in conversation %s",
                i, conversation_id,
            )
    return rows


__all__ = ["EventsLogWriter", "load_events_jsonl"]
