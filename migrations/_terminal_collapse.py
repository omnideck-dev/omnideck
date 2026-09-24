"""Shared helper: collapse terminal_output events into per-agent transcripts.

Mirrors how the UI merges terminal events — ``running`` opens a command's
entry, ``streaming`` chunks append output text, ``completed`` replaces the
entry with the full output — producing the shape stored in the
``terminal.json`` sidecar, capped at the UI's transcript ceiling.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

_MAX_ENTRIES_PER_AGENT = 50


def merge_terminal_transcripts(
    events: Iterable[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Per-agent merged command entries from flat terminal_output events.

    Accepts flat event dicts (old events.json entries and events.jsonl
    lines share the same field layout). Commands that never completed keep
    whatever streamed.
    """
    transcripts: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        if e.get("type") != "terminal_output":
            continue
        agent_id = e.get("agent_id") or ""
        lines = transcripts.setdefault(agent_id, [])
        cmd_id = e.get("cmd_id")
        status = e.get("status") or "completed"
        idx = next(
            (i for i, x in enumerate(lines) if cmd_id and x.get("cmd_id") == cmd_id),
            None,
        )
        entry = {
            "cmd_id": cmd_id,
            "cmd": e.get("cmd"),
            "status": status,
            "stdout": e.get("stdout"),
            "stderr": e.get("stderr"),
            "exit_code": e.get("exit_code"),
            "agent_id": agent_id,
            "timestamp": e.get("timestamp") or "",
        }
        if idx is None:
            lines.append(entry)
        elif status == "streaming":
            existing = lines[idx]
            existing["status"] = "streaming"
            existing["stdout"] = ((existing.get("stdout") or "") + (e.get("stdout") or "")) or None
            existing["stderr"] = ((existing.get("stderr") or "") + (e.get("stderr") or "")) or None
            existing["timestamp"] = entry["timestamp"] or existing.get("timestamp") or ""
        else:
            lines[idx] = entry
    for agent_id, lines in transcripts.items():
        if len(lines) > _MAX_ENTRIES_PER_AGENT:
            transcripts[agent_id] = lines[-_MAX_ENTRIES_PER_AGENT:]
    return transcripts


__all__ = ["merge_terminal_transcripts"]
