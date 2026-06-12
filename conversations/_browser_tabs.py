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
from typing import Any

from sdk.events import AgentEvent

from ._store import _get_conv_dir

logger = logging.getLogger(__name__)

_FILENAME = "browser_tabs.json"


def load_browser_tabs(conversation_id: str) -> list[dict[str, Any]]:
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


def save_browser_tabs(conversation_id: str, tabs: dict[str, dict[str, Any]]) -> None:
    """Write the full tab_id → snapshot map atomically."""
    conv_dir = _get_conv_dir(conversation_id)
    conv_dir.mkdir(parents=True, exist_ok=True)
    path = conv_dir / _FILENAME
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(tabs), encoding="utf-8")
    tmp.replace(path)


class BrowserTabsWriter:
    """Conversation observer that keeps browser_tabs.json current.

    Each browser_screenshot event overwrites its tab's entry, so the file
    always holds exactly the latest snapshot per tab. The existing file is
    loaded once on first write so tabs from earlier turns survive.
    """

    def __init__(self, conversation_id: str) -> None:
        self._conversation_id = conversation_id
        self._tabs: dict[str, dict[str, Any]] | None = None

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
            tab_id = str(event.payload.tab_id)
            self._tabs[tab_id] = {
                "tab_id": tab_id,
                "url": event.payload.url,
                "title": event.payload.title,
                "screenshot": event.payload.screenshot,
                "agent_id": event.agent_id,
                "timestamp": event.timestamp.isoformat(),
            }
            save_browser_tabs(self._conversation_id, self._tabs)
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "Failed to update browser tabs for '%s'", self._conversation_id,
            )


__all__ = ["BrowserTabsWriter", "load_browser_tabs", "save_browser_tabs"]
