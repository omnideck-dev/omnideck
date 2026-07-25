"""Browser interaction tools.

This module exposes helpers for interacting with the active browser page.
Each tool returns a formatted rendered-document string showing the updated page
content and interactive elements.
"""

from __future__ import annotations

import contextvars
import logging
import math
from dataclasses import replace
from typing import Any

from playwright.async_api import Error as PlaywrightError

from config import load_config
from tools.browser._tool_context import get_document
from tools.browser._tool_support import (
    _log_browser_panel,
    format_action_result,
)
from tools.browser.core.exceptions import BrowserToolError
from tools.browser.core.formatting import format_rendered_document
from tools.browser.events import emit_screenshot_after, set_result_tab

# ---------------------------------------------------------------------------
# Scroll budget tracking
# ---------------------------------------------------------------------------
# Tracks scroll calls per page URL to prevent the agent from scrolling
# endlessly. Resets when the URL changes (navigation, click-through, etc.).
# Uses contextvars so each async task (request/agent invocation) gets its own
# independent scroll budget — no cross-request interference.
_scroll_count_var: contextvars.ContextVar[int] = contextvars.ContextVar("_scroll_count", default=0)
_scroll_url_var: contextvars.ContextVar[str] = contextvars.ContextVar("_scroll_url", default="")


logger = logging.getLogger(__name__)


def _validate_bbox(
    x1: float | int,
    y1: float | int,
    x2: float | int,
    y2: float | int,
    *,
    tool_name: str,
) -> tuple[float, float, float, float]:
    """Validate and convert bounding box coordinates."""
    try:
        coords = (float(x1), float(y1), float(x2), float(y2))
    except (TypeError, ValueError) as exc:
        raise BrowserToolError("All coordinates must be numeric", tool=tool_name) from exc
    if not all(math.isfinite(c) for c in coords):
        raise BrowserToolError("All coordinates must be finite numbers", tool=tool_name)
    return coords


@emit_screenshot_after
async def click(ref: str, *, tab: str) -> str:
    """Click an element by its ref number from the rendered document.

    Always returns an updated rendered document.

    Args:
        ref: Ref number from ``browse_page()`` output.
            Examples: ``"7"``, ``"12"``.
        tab: Tab ID from new_tab() or browse_page() output.

    Returns:
        Updated rendered-document string.

    Raises:
        BrowserToolError: If the element is not found or the click fails.
    """
    clean_ref = ref.strip()
    if not clean_ref:
        msg = "ref must be a non-empty string"
        raise BrowserToolError(msg, tool="click")

    browser, resolved_tab, document = await get_document("click", tab=tab)

    try:
        resolution = await document.resolve_ref(clean_ref, tool_name="click")
    except BrowserToolError as exc:
        return str(exc)

    try:
        result = await browser.coordinate_action(
            lambda: document.click(resolution),
            source_tab=resolved_tab,
        )
        return await format_action_result(result, tool_name="click", resolution=resolution)
    except BrowserToolError as exc:
        return str(exc)
    except PlaywrightError:  # pragma: no cover - final safety net
        logger.exception("Failed to render document after click for ref %s", clean_ref)
        return "[click] Failed to complete click operation."


@emit_screenshot_after
async def press_and_hold(
    ref: str,
    duration_ms: int = 3000,
    *,
    tab: str,
) -> str:
    """Press and hold an element for a specified duration.

    Use this for bot-detection challenges that require holding a button down
    for several seconds (e.g. Walmart's press-and-hold verification).

    Args:
        ref: Ref number from ``browse_page()`` output.
            Examples: ``"7"``, ``"12"``.
        duration_ms: How long to hold the mouse button in milliseconds.
            Defaults to 3000 (3 seconds). Range: 500-10000.
        tab: Stable tab ID to act on — the ID shown in the document
            header (e.g. ``tab="3"``).

    Returns:
        Updated rendered-document string after the hold is released.

    Raises:
        BrowserToolError: If the element is not found or the hold fails.
    """
    clean_ref = ref.strip()
    if not clean_ref:
        raise BrowserToolError("ref must be a non-empty string", tool="press_and_hold")

    clamped_duration = max(500, min(10000, duration_ms))

    browser, resolved_tab, document = await get_document("press_and_hold", tab=tab)

    resolution = await document.resolve_ref(clean_ref, tool_name="press_and_hold")

    details = {
        "ref": resolution.ref,
        "duration_ms": clamped_duration,
    }

    try:
        result = await browser.coordinate_action(
            lambda: document.press_and_hold(
                resolution,
                duration_ms=clamped_duration,
            ),
            source_tab=resolved_tab,
            wait_for_navigation=False,
        )
        return await format_action_result(result, tool_name="press_and_hold", resolution=resolution)
    except BrowserToolError:
        raise
    except PlaywrightError as exc:  # pragma: no cover - final safety net
        logger.exception("Failed to complete press_and_hold for ref %s", clean_ref)
        raise BrowserToolError(
            "Failed to complete press_and_hold operation",
            tool="press_and_hold",
            details=details,
        ) from exc


@emit_screenshot_after
async def drag(
    source: str,
    target: str,
    *,
    tab: str,
) -> str:
    """Drag from a source element to a target element.

    Args:
        source: Ref number from ``browse_page()`` for the drag start element.
        target: Ref number for the drop destination.
        tab: Stable tab ID to act on — the ID shown in the document
            header (e.g. ``tab="3"``).

    Returns:
        Updated rendered-document string.

    Raises:
        BrowserToolError: If elements are not found or the drag fails.
    """
    clean_source = source.strip()
    if not clean_source:
        raise BrowserToolError("source must be a non-empty string", tool="drag")

    clean_target = target.strip()
    if not clean_target:
        raise BrowserToolError("target must be a non-empty string", tool="drag")

    browser, resolved_tab, document = await get_document("drag", tab=tab)

    source_resolution = await document.resolve_ref(clean_source, tool_name="drag")

    target_resolution = await document.resolve_ref(clean_target, tool_name="drag")

    details: dict[str, Any] = {
        "source_ref": source_resolution.ref,
        "target_ref": target_resolution.ref,
    }

    async def _perform_drag() -> None:
        await document.drag(source_resolution, target_resolution)

    try:
        browser_result = await browser.coordinate_action(
            _perform_drag,
            source_tab=resolved_tab,
            wait_for_navigation=False,
        )
    except BrowserToolError:
        raise
    except PlaywrightError as exc:
        logger.exception("Playwright error during drag for source %s", clean_source)
        msg = "Playwright error performing drag"
        raise BrowserToolError(msg, tool="drag", details=details) from exc

    return await format_action_result(browser_result, tool_name="drag", resolution=source_resolution)


@emit_screenshot_after
async def fill_field(
    ref: str,
    value: str | int | float | bool | None,
    *,
    tab: str,
) -> str:
    """Type into a text input or textarea field.

    Pass the complete text in a single call — do not call multiple times
    with individual characters. Returns an updated rendered document.

    Args:
        ref: Ref number from ``browse_page()`` output.
            Examples: ``"7"``, ``"12"``.
        value: The complete text to type (converted to string).
        tab: Stable tab ID to act on — the ID shown in the document
            header (e.g. ``tab="3"``).

    Returns:
        Updated rendered-document string.

    Raises:
        BrowserToolError: If the element is not found or is unsupported.
    """
    clean_ref = ref.strip()
    if not clean_ref:
        msg = "ref must be a non-empty string"
        raise BrowserToolError(msg, tool="fill_field")

    # Allow callers to pass None; convert to empty string for typing into fields.
    text_value = "" if value is None else str(value)

    browser, resolved_tab, document = await get_document("fill_field", tab=tab)

    resolution = await document.resolve_ref(clean_ref, tool_name="fill_field")

    async def _perform_fill() -> None:
        await document.fill_field(resolution, text_value)

    try:
        result = await browser.coordinate_action(
            _perform_fill,
            source_tab=resolved_tab,
            wait_for_navigation=False,
        )
        return await format_action_result(result, tool_name="fill_field", resolution=resolution)
    except BrowserToolError:
        raise
    except PlaywrightError as exc:
        logger.exception("Playwright error during fill_field for ref %s", clean_ref)
        msg = f"Playwright error filling element: {exc}"
        raise BrowserToolError(
            msg,
            tool="fill_field",
            details={"ref": resolution.ref},
        ) from exc


@emit_screenshot_after
async def press_keys(keys: list[str], *, tab: str) -> str:
    """Press keyboard keys on the currently focused element.

    Commonly used after ``fill_field()`` to submit a form
    (``press_keys(["Enter"])``), or to dismiss dialogs (``["Escape"]``).

    Args:
        keys: List of key names.  Examples: ``["Enter"]``, ``["Escape"]``,
            ``["ArrowDown"]``, ``["Control+Shift+P"]``.
        tab: Stable tab ID to act on — the ID shown in the document
            header (e.g. ``tab="3"``).

    Returns:
        Updated rendered-document string.

    Raises:
        BrowserToolError: If keys are invalid or key presses fail.
    """
    if not isinstance(keys, list) or len(keys) == 0:
        raise BrowserToolError("keys must be a non-empty list of key names", tool="press_keys")

    browser, resolved_tab, document = await get_document("press_keys", tab=tab)

    try:
        result = await browser.coordinate_action(
            lambda: document.press_keys(keys),
            source_tab=resolved_tab,
        )
        return await format_action_result(result, tool_name="press_keys")
    except BrowserToolError:
        raise
    except PlaywrightError as exc:
        logger.exception("Playwright error during press_keys for keys %s", keys)
        msg = f"Playwright error pressing keys: {exc}"
        raise BrowserToolError(msg, tool="press_keys") from exc


@emit_screenshot_after
async def scroll_page(
    direction: str = "down",
    amount: int | None = None,
    *,
    tab: str,
) -> str:
    """Scroll the page and return an updated rendered document.

    A scroll budget is enforced per URL.  After several scrolls a warning
    appears; after the hard limit, scrolling is refused.  Use
    ``browse_page(full_page=True)`` or ``save_page_content()`` instead of
    excessive scrolling.

    Args:
        direction: ``"down"``, ``"up"``, ``"page_down"``, ``"page_up"``,
            ``"top"``, or ``"bottom"``.
        amount: Optional pixel distance for ``"down"``/``"up"``.  Omit for
            a viewport-sized scroll.
        tab: Stable tab ID to act on — the ID shown in the document
            header (e.g. ``tab="3"``).

    Returns:
        Updated rendered-document string with scroll state.

    Raises:
        BrowserToolError: If direction is invalid or scroll budget exhausted.
    """
    if not isinstance(direction, str) or not direction:
        raise BrowserToolError("direction must be a non-empty string", tool="scroll_page")

    browser, resolved_tab, document = await get_document("scroll_page", tab=tab)

    cfg = load_config()
    warn_threshold = cfg.tools.browser.scroll_warn_threshold
    hard_limit = cfg.tools.browser.scroll_hard_limit

    scroll_count = _scroll_count_var.get()
    scroll_url = _scroll_url_var.get()

    # Reset counter when the page URL changes (navigation, click-through, etc.)
    if resolved_tab.url != scroll_url:
        _scroll_url_var.set(resolved_tab.url)
        scroll_count = 0

    # Hard limit: refuse to scroll further
    if scroll_count >= hard_limit:
        raise BrowserToolError(
            f"Scroll limit reached ({hard_limit} scrolls on this page). "
            "STOP scrolling. Use browse_page(full_page=True) to read the entire page, "
            "or save_page_content(filename) to save it as markdown for processing.",
            tool="scroll_page",
        )

    scroll_count += 1
    _scroll_count_var.set(scroll_count)

    try:
        interaction_result = await browser.coordinate_action(
            lambda: document.scroll(direction, amount),
            source_tab=resolved_tab,
            wait_for_navigation=False,
        )
    except BrowserToolError:
        raise
    except PlaywrightError as exc:
        logger.exception("Playwright error during scroll_page for direction %s", direction)
        raise BrowserToolError(f"Playwright error performing scroll: {exc}", tool="scroll_page") from exc

    # Render the document with updated viewport/scroll information.
    result_tab = interaction_result.tab
    set_result_tab(result_tab)
    rendered = await result_tab.render_document(interaction_result.navigation_response)
    _log_browser_panel(interaction_result, rendered=rendered, tool_name="scroll_page")

    content = rendered.content
    # Inject warning after threshold
    if scroll_count >= warn_threshold:
        remaining = hard_limit - scroll_count
        content += (
            f"\n\n--- SCROLL WARNING ({scroll_count}/{hard_limit}) ---\n"
            f"You have {remaining} scroll(s) left on this page. "
            "STOP scrolling and answer with what you have, OR use "
            "browse_page(full_page=True) to read the entire page at once.\n"
            "---\n"
        )

    return format_rendered_document(replace(rendered, content=content), tab_id=result_tab.id)


__all__ = [
    "click",
    "drag",
    "fill_field",
    "press_and_hold",
    "press_keys",
    "scroll_page",
]
