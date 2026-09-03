"""Browser tools for tab-aware URL and history navigation."""

from __future__ import annotations

import logging

from playwright.async_api import Error as PlaywrightError

from browser.core.exceptions import BrowserToolError
from browser.runtime import get_browser
from tools.browser._tool_context import get_document, get_tab
from tools.browser._tool_support import format_action_result
from tools.browser.events import emit_screenshot, emit_screenshot_after, emit_tab_state

logger = logging.getLogger(__name__)


@emit_screenshot_after
async def goto(url: str, *, tab: str) -> str:
    """Navigate an existing tab to ``url`` and return its rendered document.

    ``goto`` only re-points a tab that already exists.  To open a fresh
    page, use ``new_tab(url)`` — that is the only way to create a tab.

    Two concurrent ``goto`` calls on the same tab error — open
    pages in parallel with ``new_tab(url)`` instead.

    Args:
        url: The URL to navigate to.
        tab: Stable tab ID to navigate — pass the ID shown in the
            document header (e.g. ``tab="3"``).

    Returns:
        Annotated rendered document for the navigated tab.

    Raises:
        BrowserToolError: If the tab is unavailable or navigation fails.
    """
    try:
        browser, resolved_tab = await get_tab("goto", tab=tab)
        result = await browser.navigate(url, tab=resolved_tab)
        return await format_action_result(result, tool_name="goto")
    except BrowserToolError:
        raise
    except Exception as exc:  # pragma: no cover - wrap into tool error
        logger.exception("goto failed for %s", url)
        raise BrowserToolError(str(exc), tool="goto") from exc


async def new_tab(url: str) -> str:
    """Open a new tab at ``url`` and return its rendered document.

    Use this when you want to keep the current page intact and inspect
    something else in addition — e.g. opening a search result without
    losing the listing, or fetching several pages in parallel.

    Args:
        url: The URL the new tab should navigate to.

    Returns:
        Annotated rendered document for the new tab. The header carries the
        new tab's ID (``tab=N``) — use that ID on subsequent tools to
        act on this tab.

    Raises:
        BrowserToolError: If the tab limit is reached or navigation fails.
    """
    try:
        browser = await get_browser()
        resolved_tab = await browser.new_tab()
        result = await browser.navigate(url, tab=resolved_tab)
        formatted = await format_action_result(result, tool_name="new_tab")
        # new_tab is the one tool that doesn't take a ``tab`` kwarg, so
        # it emits its own screenshot explicitly rather than going through
        # the @emit_screenshot_after decorator.
        await emit_screenshot(resolved_tab)
        return formatted
    except BrowserToolError:
        raise
    except Exception as exc:  # pragma: no cover - wrap into tool error
        logger.exception("new_tab failed for %s", url)
        raise BrowserToolError(str(exc), tool="new_tab") from exc


async def close_tab(*, tab: str) -> str:
    """Close a tab and free its resources.

    Closing a tab does not free its ID. A later call that references the
    closed tab errors with the open-tab listing rather than acting on a
    different tab.

    Args:
        tab: Stable ID of the tab to close.

    Returns:
        Confirmation line naming the closed tab.

    Raises:
        BrowserToolError: If the tab does not exist or cannot be closed.
    """
    try:
        browser, resolved_tab = await get_tab("close_tab", tab=tab)
        closed_id = resolved_tab.id
        await resolved_tab.close()
        # close_tab produces no screenshot, so emit the reduced open-tab set
        # explicitly to prune the closed tab from the UI's record.
        await emit_tab_state()
        return f"Closed tab={closed_id}."
    except BrowserToolError:
        raise
    except Exception as exc:  # pragma: no cover - wrap into tool error
        logger.exception("close_tab failed for %s", tab)
        raise BrowserToolError(str(exc), tool="close_tab") from exc


@emit_screenshot_after
async def go_back(*, tab: str) -> str:
    """Navigate back in browser history and return an updated rendered document.

    Args:
        tab: Tab ID to act on.

    Returns:
        Updated rendered-document string.

    Raises:
        BrowserToolError: If back navigation fails.
    """
    browser, resolved_tab, _document = await get_document("go_back", tab=tab)

    try:
        browser_result = await browser.navigate_back(tab=resolved_tab)
    except BrowserToolError:
        raise
    except PlaywrightError as exc:
        logger.exception("Playwright error during go_back")
        raise BrowserToolError("Failed to navigate back", tool="go_back") from exc

    return await format_action_result(browser_result, tool_name="go_back")


__all__ = ["close_tab", "go_back", "goto", "new_tab"]
