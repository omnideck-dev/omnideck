"""Strip browser_screenshot events from already-converted events.jsonl logs.

The events-first migration now keeps screenshots out of the log entirely
(latest-per-tab goes to the browser_tabs.json sidecar), but stores that
converted before that change carry every screenshot ever taken — real logs
were >90% base64 pixels. This pass rewrites those logs without the
screenshot lines, preserving the final snapshot per tab in the sidecar.

No-op for conversations with no screenshot events, so fresh installs and
already-scrubbed stores pass straight through.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from migrations._backup import backup_file
from migrations._screenshot_prune import latest_tab_snapshots

logger = logging.getLogger(__name__)

_NAME = "008_scrub_browser_screenshots"


def _scrub_log(state_dir: Path, log_path: Path) -> int:
    """Rewrite one events.jsonl without screenshot lines. Returns the count
    of lines removed (0 = file untouched)."""
    kept: list[str] = []
    shots: list[dict] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            kept.append(line)
            continue
        if event.get("type") == "browser_screenshot":
            shots.append(event)
        else:
            kept.append(line)

    if not shots:
        return 0

    backup_file(state_dir, _NAME, log_path)

    # Final snapshot per tab survives into the sidecar. A sidecar written
    # by the live app since the upgrade is newer than anything in the log,
    # so existing entries win over log-derived ones.
    conv_dir = log_path.parent
    tabs = latest_tab_snapshots(shots)
    sidecar = conv_dir / "browser_tabs.json"
    if sidecar.exists():
        try:
            existing = json.loads(sidecar.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                tabs.update(existing)
        except Exception:
            logger.exception("Unreadable %s; overwriting from log", sidecar)
    tabs_tmp = sidecar.with_suffix(".tmp")
    tabs_tmp.write_text(json.dumps(tabs), encoding="utf-8")
    tabs_tmp.replace(sidecar)

    tmp = log_path.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(line + "\n" for line in kept), encoding="utf-8")
    tmp.replace(log_path)
    return len(shots)


def migrate(state_dir: Path) -> None:
    """Scrub screenshot events from every conversation's events.jsonl."""
    conv_root = state_dir / "conversations"
    if not conv_root.is_dir():
        return
    scrubbed = 0
    removed = 0
    for conv_dir in sorted(conv_root.iterdir()):
        log_path = conv_dir / "events.jsonl"
        if not log_path.is_file():
            continue
        try:
            n = _scrub_log(state_dir, log_path)
        except Exception:
            logger.exception("Failed to scrub %s; leaving it untouched", log_path)
            continue
        if n:
            scrubbed += 1
            removed += n
    if scrubbed:
        logger.info(
            "Scrubbed %d screenshot event(s) from %d conversation log(s)",
            removed, scrubbed,
        )
