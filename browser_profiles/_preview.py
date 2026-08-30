"""Short-lived Browser-state previews reused by an explicit save."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any

from tools.browser.core.browser import Browser

_PREVIEW_TTL_SECONDS = 300
_MAX_PREVIEWS = 8


@dataclass(slots=True)
class _Preview:
    scope: str
    browser: Browser
    storage_state: dict[str, Any]
    created_at: float


class BrowserStatePreviewCache:
    """Bounded, short-lived cache tying a save preview to one live Browser."""

    def __init__(self) -> None:
        self._previews: dict[str, _Preview] = {}

    def discard_expired(self, now: float) -> None:
        for token, preview in list(self._previews.items()):
            if now - preview.created_at > _PREVIEW_TTL_SECONDS:
                self._previews.pop(token, None)
        while len(self._previews) >= _MAX_PREVIEWS:
            oldest = min(self._previews, key=lambda item: self._previews[item].created_at)
            self._previews.pop(oldest, None)

    def put(self, preview: _Preview) -> str:
        self.discard_expired(preview.created_at)
        token = secrets.token_urlsafe(24)
        self._previews[token] = preview
        return token

    def consume(self, token: str | None) -> _Preview | None:
        if not token:
            return None
        return self._previews.pop(token, None)

    def clear(self) -> None:
        self._previews.clear()


_cache = BrowserStatePreviewCache()


async def capture_browser_state_preview(
    browser: Browser,
    *,
    scope: str,
) -> tuple[str, dict[str, Any]]:
    """Capture state once for both the read-only preview and subsequent save."""
    storage_state = await browser.capture_storage_state()
    now = time.monotonic()
    token = _cache.put(
        _Preview(
            scope=scope,
            browser=browser,
            storage_state=storage_state,
            created_at=now,
        )
    )
    return token, storage_state


def consume_browser_state_preview(
    token: str | None,
    *,
    scope: str,
    browser: Browser,
) -> dict[str, Any] | None:
    """Consume a valid preview for the same live Browser and request scope."""
    preview = _cache.consume(token)
    if preview is None:
        return None
    if time.monotonic() - preview.created_at > _PREVIEW_TTL_SECONDS:
        return None
    if preview.scope != scope or preview.browser is not browser:
        return None
    return preview.storage_state


def reset_browser_state_previews() -> None:
    """Clear captured previews, primarily for isolated application tests."""
    _cache.clear()


__all__ = [
    "BrowserStatePreviewCache",
    "capture_browser_state_preview",
    "consume_browser_state_preview",
    "reset_browser_state_previews",
]
