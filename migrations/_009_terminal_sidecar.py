"""Move terminal_output events out of converted events.jsonl logs.

The events-first conversion now routes terminal output to the bounded
``terminal.json`` sidecar, but stores converted by an earlier build carry
every command's streaming chunks and completed output in the log — output
stored twice, growing forever for a panel that shows the last N commands.
This pass collapses those events into the sidecar and rewrites the log
without them.

No-op for conversations with no terminal events, so fresh installs and
already-converted stores pass straight through.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from migrations._backup import backup_file
from migrations._terminal_collapse import merge_terminal_transcripts

logger = logging.getLogger(__name__)

_NAME = "009_terminal_sidecar"


def _collapse_log(state_dir: Path, log_path: Path) -> int:
    """Rewrite one events.jsonl without terminal_output lines. Returns the
    count of lines removed (0 = file untouched)."""
    kept: list[str] = []
    terminal_events: list[dict] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            kept.append(line)
            continue
        if event.get("type") == "terminal_output":
            terminal_events.append(event)
        else:
            kept.append(line)

    if not terminal_events:
        return 0

    backup_file(state_dir, _NAME, log_path)

    # A sidecar written by the live app since the upgrade is newer than
    # anything in the log, so existing agent transcripts win.
    conv_dir = log_path.parent
    transcripts = merge_terminal_transcripts(terminal_events)
    sidecar = conv_dir / "terminal.json"
    if sidecar.exists():
        try:
            existing = json.loads(sidecar.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                transcripts.update(existing)
        except Exception:
            logger.exception("Unreadable %s; overwriting from log", sidecar)
    term_tmp = sidecar.with_suffix(".tmp")
    term_tmp.write_text(json.dumps(transcripts), encoding="utf-8")
    term_tmp.replace(sidecar)

    tmp = log_path.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(line + "\n" for line in kept), encoding="utf-8")
    tmp.replace(log_path)
    return len(terminal_events)


def migrate(state_dir: Path) -> None:
    """Collapse terminal events from every conversation's events.jsonl."""
    conv_root = state_dir / "conversations"
    if not conv_root.is_dir():
        return
    collapsed = 0
    removed = 0
    for conv_dir in sorted(conv_root.iterdir()):
        log_path = conv_dir / "events.jsonl"
        if not log_path.is_file():
            continue
        try:
            n = _collapse_log(state_dir, log_path)
        except Exception:
            logger.exception("Failed to collapse %s; leaving it untouched", log_path)
            continue
        if n:
            collapsed += 1
            removed += n
    if collapsed:
        logger.info(
            "Moved %d terminal event(s) from %d conversation log(s) into sidecars",
            removed, collapsed,
        )
