"""Browser tool event emission helpers.

This module provides a single ``_emit_screenshot`` function that captures a
JPEG screenshot from a Playwright page and publishes it as a
``BrowserScreenshotPayload`` event for the UI.

Screenshots are emitted at two points:

- **Post-tool** — ``emit_screenshot_after`` decorator calls
  ``_emit_screenshot`` once after a tool returns a result with a page view.
- **Ad-hoc** — ``javascript.py`` calls ``emit_screenshot`` directly after
  JS evaluation.

The live, high-frame-rate view of the selected tab is served separately by the
browser control side channel (CDP screencast), so these screenshots only need
to cover thumbnails and post-action state.
"""

from __future__ import annotations

import base64
import logging
import time
from collections.abc import Callable
from functools import wraps
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import Page

from tools.browser.core import get_browser

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Core screenshot capture + publish
# ---------------------------------------------------------------------------


async def _emit_screenshot(page: Page) -> None:
    """Capture a JPEG screenshot from *page* and publish it as a browser event.

    This is the single code path for all screenshot emission.  Uses JPEG at
    reduced quality for fast encoding and small payloads.
    """
    from sdk.events import (
        AgentEvent,
        BrowserScreenshotPayload,
        publish_event,
    )

    url = getattr(page, "url", "")
    closed = page.is_closed() if hasattr(page, "is_closed") else "unknown"

    # Context state for diagnostics.
    try:
        n_pages = len(page.context.pages)
    except Exception:  # noqa: BLE001
        n_pages = -1

    t0 = time.monotonic()
    try:
        screenshot_bytes = await page.screenshot(
            type="jpeg", quality=55, timeout=5000,
        )
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.warning(
            "Screenshot capture failed after %.0fms "
            "(page=%s, closed=%s, pages_in_ctx=%d): %s",
            elapsed_ms, url, closed, n_pages, exc,
        )
        return

    elapsed_ms = (time.monotonic() - t0) * 1000
    if elapsed_ms > 2000:
        logger.warning(
            "Screenshot capture slow: %.0fms (page=%s, pages_in_ctx=%d)",
            elapsed_ms, url, n_pages,
        )
    else:
        logger.debug("Screenshot captured in %.0fms (page=%s)", elapsed_ms, url)

    screenshot_base64 = base64.b64encode(screenshot_bytes).decode("utf-8")

    try:
        title = await page.title()
    except Exception:  # noqa: BLE001
        title = ""

    # Tag the event with the tab ID so the UI can route each screenshot
    # to its own thumbnail slot.
    browser = await get_browser()
    tab_id = browser.tab_id_of(page)
    # Carry the live open-tab id set so the UI can prune thumbnails for tabs
    # that have since closed (it otherwise keeps stale per-tab snapshots).
    open_tab_ids = [t for t in (browser.tab_id_of(p) for p in browser.open_tabs()) if t is not None]

    publish_event(AgentEvent(payload=BrowserScreenshotPayload(
        type="browser_screenshot",
        url=url,
        title=title,
        screenshot=screenshot_base64,
        tab_id=tab_id,
        open_tab_ids=open_tab_ids,
    )))


async def emit_screenshot(page: Page) -> None:
    """Public wrapper around ``_emit_screenshot`` for use by other modules.

    Swallows all exceptions so callers never fail due to screenshot capture.
    """
    try:
        await _emit_screenshot(page)
    except Exception as exc:  # noqa: BLE001
        url = getattr(page, "url", "unknown")
        closed = page.is_closed() if hasattr(page, "is_closed") else "?"
        logger.warning(
            "Screenshot failed (page=%s, closed=%s)", url, closed,
            exc_info=True,
        )


async def emit_tab_state() -> None:
    """Emit a screenshot-less event carrying just the current open-tab set.

    Lets the UI reconcile its per-tab snapshots when no screenshot is produced —
    notably after a tab closes (which has no page to screenshot), so the closed
    tab is pruned even when it was the last one open.
    """
    from sdk.events import AgentEvent, BrowserScreenshotPayload, publish_event

    try:
        browser = await get_browser()
        open_tab_ids = [t for t in (browser.tab_id_of(p) for p in browser.open_tabs()) if t is not None]
        publish_event(AgentEvent(payload=BrowserScreenshotPayload(
            type="browser_screenshot",
            url="",
            title="",
            screenshot=None,
            tab_id=None,
            open_tab_ids=open_tab_ids,
        )))
    except Exception:  # noqa: BLE001 - best-effort reconcile, never fail the tool
        logger.warning("Failed to emit tab-state reconcile", exc_info=True)


# ---------------------------------------------------------------------------
# Post-tool screenshot decorator
# ---------------------------------------------------------------------------


def emit_screenshot_after[F: Callable[..., Any]](func: F) -> F:
    """Decorator that emits a browser screenshot after the wrapped tool runs.

    Wraps browser tool functions that return a page view string.
    After the tool completes, captures a screenshot via
    ``_emit_screenshot`` and publishes it to the UI.  The screenshot is NOT
    included in the tool's return value to avoid wasting context tokens.

    All settling (network idle, DOM quiet, CSS animations) is handled by
    ``wait_for_page_settle`` inside ``perform_interaction`` — this
    decorator only captures the screenshot.
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = await func(*args, **kwargs)

        # Screenshot the tab the tool acted on, identified by the `tab`
        # kwarg.  Tools that don't take a tab (new_tab, which creates one)
        # emit their own screenshot explicitly; the decorator just skips
        # them silently.
        tab = kwargs.get("tab")
        if tab is None:
            return result
        page = None
        try:
            browser = await get_browser()
            page = browser.resolve_tab(tab)
            if page is not None and not page.is_closed():
                logger.debug(
                    "Post-tool screenshot for %s (tab=%s, page=%s)",
                    func.__name__, tab, getattr(page, "url", "?"),
                )
                await _emit_screenshot(page)
        except Exception:  # noqa: BLE001 - never fail the tool call
            page_url = getattr(page, "url", "unknown") if page else "no page"
            closed = page.is_closed() if page and hasattr(page, "is_closed") else "?"
            logger.warning(
                "Post-tool screenshot failed for %s (page=%s, closed=%s)",
                func.__name__, page_url, closed, exc_info=True,
            )

        return result

    return wrapper  # type: ignore


__all__ = [
    "emit_screenshot",
    "emit_screenshot_after",
    "emit_tab_state",
]
