"""Latest-per-tab browser snapshot sidecar for a conversation.

Browser screenshots are UI state, not conversation history: the preview
panel only ever shows the most recent snapshot of each tab, so persisting
every screenshot into the append-only event log just bloats it with
base64 (real logs were >90% pixels). Instead, the latest snapshot per tab
lives in an overwrite-in-place ``browser_tabs.json`` next to the
conversation — same pattern as the preview-panel state.
"""

from __future__ import annotations

import json
import logging
from typing import TypedDict

from sdk.events import AgentEvent

from ._store import _get_conv_dir

logger = logging.getLogger(__name__)

_FILENAME = "browser_tabs.json"


class BrowserTabSnapshot(TypedDict):
    """One tab's latest snapshot as persisted in browser_tabs.json."""

    tab_id: str
    url: str
    title: str
    screenshot: str
    agent_id: str | None
    timestamp: str


def load_browser_tabs(conversation_id: str) -> list[BrowserTabSnapshot]:
    """The saved latest-per-tab browser snapshots, or [] when none exist."""
    path = _get_conv_dir(conversation_id) / _FILENAME
    if not path.exists():
        return []
    try:
        tabs = json.loads(path.read_text(encoding="utf-8"))
        return list(tabs.values()) if isinstance(tabs, dict) else []
    except Exception:
        logger.exception("Failed to read %s", path)
        return []


def save_browser_tabs(conversation_id: str, tabs: dict[str, BrowserTabSnapshot]) -> None:
    """Write the full tab_id → snapshot map atomically."""
    conv_dir = _get_conv_dir(conversation_id)
    conv_dir.mkdir(parents=True, exist_ok=True)
    path = conv_dir / _FILENAME
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(tabs), encoding="utf-8")
    tmp.replace(path)


class BrowserTabsWriter:
    """Conversation observer that keeps browser_tabs.json current.

    A screenshot-bearing event overwrites its tab's entry, so the file always
    holds exactly the latest snapshot per tab. A screenshot-less event is
    reconcile-only (e.g. emitted after a tab closes, which has no page to
    capture): it carries just the open-tab set and prunes snapshots for tabs
    that have since closed. The existing file is loaded once on first write so
    tabs from earlier turns survive.
    """

    def __init__(self, conversation_id: str) -> None:
        self._conversation_id = conversation_id
        self._tabs: dict[str, BrowserTabSnapshot] | None = None

    def handle_event(self, event: AgentEvent) -> None:
        """Record a browser_screenshot event; ignore everything else."""
        if event.payload.type != "browser_screenshot":
            return
        try:
            if self._tabs is None:
                path = _get_conv_dir(self._conversation_id) / _FILENAME
                self._tabs = {}
                if path.exists():
                    loaded = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        self._tabs = loaded
            payload = event.payload
            shot = payload.screenshot
            has_shot = shot is not None
            if shot is not None:
                tab_id = str(payload.tab_id)
                self._tabs[tab_id] = {
                    "tab_id": tab_id,
                    "url": payload.url,
                    "title": payload.title,
                    "screenshot": shot,
                    "agent_id": event.agent_id,
                    "timestamp": event.timestamp.isoformat(),
                }
            # Reconcile against the live open-tab set so snapshots for tabs that
            # have since closed are pruned instead of lingering. The set comes
            # straight from the live page list, so a tab that's still open is
            # always in it and its fresh snapshot survives; one that has closed
            # is dropped here.
            if payload.open_tab_ids is not None:
                keep = {str(t) for t in payload.open_tab_ids}
                self._tabs = {k: v for k, v in self._tabs.items() if k in keep}
            elif not has_shot:
                # Nothing to record and no open-tab set to reconcile against.
                return
            save_browser_tabs(self._conversation_id, self._tabs)
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "Failed to update browser tabs for '%s'", self._conversation_id,
            )


__all__ = ["BrowserTabsWriter", "load_browser_tabs", "save_browser_tabs"]
