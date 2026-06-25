"""Per-agent terminal transcript sidecar for a conversation.

The terminal panel is UI state, not conversation history: the model-facing
record of a command lives in its tool_result event, and the panel shows at
most the last 50 commands per agent. So instead of appending every command's
output to the event log forever, the merged transcript lives in an
overwrite-in-place ``terminal.json`` — same pattern as the browser-tab
snapshots.

Streaming chunks never touch disk: the completed event carries the full
joined output, so only the running/completed pair is recorded.
"""

from __future__ import annotations

import json
import logging
from typing import TypedDict

from sdk.events import AgentEvent

from ._store import _get_conv_dir

logger = logging.getLogger(__name__)

_FILENAME = "terminal.json"

# Mirrors the UI's transcript ceiling — entries beyond this are never shown.
_MAX_ENTRIES_PER_AGENT = 50


class TerminalEntry(TypedDict):
    """One command's running/completed record as persisted in terminal.json."""

    cmd_id: str
    cmd: str
    status: str
    stdout: str | None
    stderr: str | None
    exit_code: int | None
    agent_id: str
    timestamp: str


def load_terminal(conversation_id: str) -> dict[str, list[TerminalEntry]]:
    """The saved per-agent terminal transcripts, or {} when none exist."""
    path = _get_conv_dir(conversation_id) / _FILENAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.exception("Failed to read %s", path)
        return {}


def save_terminal(
    conversation_id: str, transcripts: dict[str, list[TerminalEntry]],
) -> None:
    """Write the full agent_id → entries map atomically."""
    conv_dir = _get_conv_dir(conversation_id)
    conv_dir.mkdir(parents=True, exist_ok=True)
    path = conv_dir / _FILENAME
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(transcripts), encoding="utf-8")
    tmp.replace(path)


class TerminalWriter:
    """Conversation observer that keeps terminal.json current.

    A command's ``running`` event opens its entry; ``completed`` replaces it
    with the full output (matching how the UI merges). ``streaming`` chunks
    are ignored — they're live-display only. Entries are capped per agent at
    the UI's transcript ceiling.
    """

    def __init__(self, conversation_id: str) -> None:
        self._conversation_id = conversation_id
        self._transcripts: dict[str, list[TerminalEntry]] | None = None

    def handle_event(self, event: AgentEvent) -> None:
        """Record a terminal_output running/completed event; ignore the rest."""
        if event.payload.type != "terminal_output":
            return
        if event.payload.status == "streaming":
            return
        agent_id = event.agent_id or ""
        try:
            if self._transcripts is None:
                self._transcripts = load_terminal(self._conversation_id)
            entry: TerminalEntry = {
                "cmd_id": event.payload.cmd_id,
                "cmd": event.payload.cmd,
                "status": event.payload.status,
                "stdout": event.payload.stdout,
                "stderr": event.payload.stderr,
                "exit_code": event.payload.exit_code,
                "agent_id": agent_id,
                "timestamp": event.timestamp.isoformat(),
            }
            lines = self._transcripts.setdefault(agent_id, [])
            idx = next(
                (i for i, e in enumerate(lines) if e.get("cmd_id") == entry["cmd_id"]),
                None,
            )
            if idx is None:
                lines.append(entry)
            else:
                lines[idx] = entry
            if len(lines) > _MAX_ENTRIES_PER_AGENT:
                del lines[: len(lines) - _MAX_ENTRIES_PER_AGENT]
            save_terminal(self._conversation_id, self._transcripts)
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "Failed to update terminal transcript for '%s'", self._conversation_id,
            )


__all__ = ["TerminalWriter", "load_terminal", "save_terminal"]
