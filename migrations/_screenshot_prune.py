"""Shared helper: reduce browser_screenshot events to latest-per-tab.

The UI only ever shows the most recent snapshot of each browser tab, so
migrations that move screenshots out of conversation logs keep just the
final snapshot per tab, shaped for the ``browser_tabs.json`` sidecar.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def latest_tab_snapshots(events: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The last browser_screenshot per tab, keyed by tab id.

    Accepts flat event dicts (old events.json entries and events.jsonl
    lines share the same flat field layout). Events without a tab_id are
    keyed under "0" — pre-tab-id logs had a single tab, so last-wins is
    the correct collapse.
    """
    tabs: dict[str, dict[str, Any]] = {}
    for e in events:
        if e.get("type") != "browser_screenshot":
            continue
        tab_id = str(e.get("tab_id") or 0)
        tabs[tab_id] = {
            "tab_id": tab_id,
            "url": e.get("url") or "",
            "title": e.get("title") or "",
            "screenshot": e.get("screenshot") or "",
            "agent_id": e.get("agent_id") or None,
            "timestamp": e.get("timestamp") or "",
        }
    return tabs


__all__ = ["latest_tab_snapshots"]
