"""Browser tool event emission helpers.

This module provides a single ``_emit_screenshot`` function that captures a
JPEG screenshot from a Playwright page and publishes it as a
``BrowserScreenshotPayload`` event for the UI.

Screenshots are emitted at two points:

- **Post-tool** — ``emit_screenshot_after`` decorator calls
  ``_emit_screenshot`` once after a tool returns a rendered document.
- **Ad-hoc** — ``scripting.py`` calls ``emit_screenshot`` directly after
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
from contextvars import ContextVar
from functools import wraps
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from browser.core.tab import Tab

from browser.runtime import get_browser

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Core screenshot capture + publish
# ---------------------------------------------------------------------------


async def _emit_screenshot(tab: Tab) -> None:
    """Capture a JPEG screenshot from *tab* and publish it as a browser event.

    This is the single code path for all screenshot emission.  Uses JPEG at
    reduced quality for fast encoding and small payloads.
    """
    from agent_core.events import (
        AgentEvent,
        BrowserScreenshotPayload,
        publish_event,
    )

    url = tab.url
    closed = tab.is_closed()

    t0 = time.monotonic()
    # Only the foreground tab can be captured; a background tab's compositor is
    # idle and capture blocks until the timeout. Under concurrent tool calls a
    # tab can be backgrounded by a sibling action before its shot fires, so keep
    # the wait short — a miss costs ~1s (logged below) and the thumbnail keeps
    # its last frame, rather than stalling the agent's path.
    try:
        screenshot_bytes = await tab.screenshot(
            image_type="jpeg",
            quality=55,
            timeout_ms=1000,
        )
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.warning(
            "Screenshot capture failed after %.0fms (tab=%s, page=%s, closed=%s): %s",
            elapsed_ms,
            tab.id,
            url,
            closed,
            exc,
        )
        return

    elapsed_ms = (time.monotonic() - t0) * 1000
    if elapsed_ms > 2000:
        logger.warning(
            "Screenshot capture slow: %.0fms (tab=%s, page=%s)",
            elapsed_ms,
            tab.id,
            url,
        )
    else:
        logger.debug("Screenshot captured in %.0fms (page=%s)", elapsed_ms, url)

    screenshot_base64 = base64.b64encode(screenshot_bytes).decode("utf-8")

    try:
        title = await tab.title()
    except Exception:  # noqa: BLE001
        title = ""

    # Tag the event with the tab ID so the UI can route each screenshot
    # to its own thumbnail slot.
    browser = await get_browser()
    # Carry the live open-tab id set so the UI can prune thumbnails for tabs
    # that have since closed (it otherwise keeps stale per-tab views).
    open_tab_ids = [tab.id for tab in browser.tabs()]

    publish_event(
        AgentEvent(
            payload=BrowserScreenshotPayload(
                type="browser_screenshot",
                url=url,
                title=title,
                screenshot=screenshot_base64,
                tab_id=tab.id,
                open_tab_ids=open_tab_ids,
            )
        )
    )


async def emit_screenshot(tab: Tab) -> None:
    """Public wrapper around ``_emit_screenshot`` for use by other modules.

    Swallows all exceptions so callers never fail due to screenshot capture.
    """
    try:
        await _emit_screenshot(tab)
    except Exception:  # noqa: BLE001
        url = tab.url
        closed = tab.is_closed()
        logger.warning(
            "Screenshot failed (page=%s, closed=%s)",
            url,
            closed,
            exc_info=True,
        )


async def emit_tab_state() -> None:
    """Emit a screenshot-less event carrying just the current open-tab set.

    Lets the UI reconcile its per-tab views when no screenshot is produced —
    notably after a tab closes (which has no page to screenshot), so the closed
    tab is pruned even when it was the last one open.
    """
    from agent_core.events import AgentEvent, BrowserScreenshotPayload, publish_event

    try:
        browser = await get_browser()
        open_tab_ids = [tab.id for tab in browser.tabs()]
        publish_event(
            AgentEvent(
                payload=BrowserScreenshotPayload(
                    type="browser_screenshot",
                    url="",
                    title="",
                    screenshot=None,
                    tab_id=None,
                    open_tab_ids=open_tab_ids,
                )
            )
        )
    except Exception:  # noqa: BLE001 - best-effort reconcile, never fail the tool
        logger.warning("Failed to emit tab-state reconcile", exc_info=True)


# ---------------------------------------------------------------------------
# Post-tool screenshot decorator
# ---------------------------------------------------------------------------


# The tab the running interaction finished on.  An interaction does not always
# end on the tab it was called with — clicking a link that targets a new tab
# leaves the agent in that new tab — and the screenshot has to show where the
# agent actually ended up, not where it started.  This is task-local, so
# concurrent tool calls never see each other's value.
_result_tab: ContextVar[Tab | None] = ContextVar("browser_result_tab", default=None)


def set_result_tab(tab: Tab | None) -> None:
    """Record the tab the running interaction finished on."""
    _result_tab.set(tab)


def emit_screenshot_after[F: Callable[..., Any]](func: F) -> F:
    """Decorator that emits a browser screenshot after the wrapped tool runs.

    Wraps browser tool functions that return a rendered-document string.
    After the tool completes, captures a screenshot via
    ``_emit_screenshot`` and publishes it to the UI.  The screenshot is NOT
    included in the tool's return value to avoid wasting context tokens.

    Page-load, DOM, font, and animation settling happens at the render-return
    boundary immediately before the tool returns — this decorator only captures
    the screenshot.
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        # Start clean so this call can only ever read a tab its own interaction
        # settled on, never one left behind by an earlier call in this task.
        token = _result_tab.set(None)
        try:
            result = await func(*args, **kwargs)
            settled = _result_tab.get()
        finally:
            _result_tab.reset(token)

        # Screenshot the tab the interaction finished on.  It reports that tab
        # itself when it moved (a click that opened one); otherwise fall back to
        # the `tab` kwarg the tool was called with.  Tools that don't take a tab
        # (new_tab, which creates one) emit their own screenshot explicitly; the
        # decorator just skips them silently.
        requested_tab = kwargs.get("tab")
        if settled is None and not isinstance(requested_tab, str | int):
            return result
        resolved_tab = None
        try:
            browser = await get_browser()
            if settled is not None:
                resolved_tab = settled
            elif isinstance(requested_tab, str | int):
                resolved_tab = browser.get_tab(requested_tab)
            if resolved_tab is not None and not resolved_tab.is_closed():
                logger.debug(
                    "Post-tool screenshot for %s (tab=%s, url=%s)",
                    func.__name__,
                    resolved_tab.id,
                    resolved_tab.url,
                )
                await _emit_screenshot(resolved_tab)
        except Exception:  # noqa: BLE001 - never fail the tool call
            page_url = resolved_tab.url if resolved_tab else "no page"
            closed = resolved_tab.is_closed() if resolved_tab else "?"
            logger.warning(
                "Post-tool screenshot failed for %s (page=%s, closed=%s)",
                func.__name__,
                page_url,
                closed,
                exc_info=True,
            )

        return result

    return wrapper  # type: ignore


__all__ = [
    "emit_screenshot",
    "emit_screenshot_after",
    "emit_tab_state",
    "set_result_tab",
]
