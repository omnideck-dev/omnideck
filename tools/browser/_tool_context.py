"""Resolve Browser, Tab, and Document state at the agent-tool boundary."""

from playwright.async_api import Error as PlaywrightError

from browser.core.browser import Browser
from browser.core.document import Document
from browser.core.exceptions import BrowserToolError
from browser.core.tab import Tab
from browser.runtime import get_browser


async def get_document(
    tool_name: str,
    *,
    tab: str,
) -> tuple[Browser, Tab, Document]:
    """Resolve one tool call's browser, tab, and selected document."""
    try:
        browser, resolved_tab = await get_tab(tool_name, tab=tab)
        document = await resolved_tab.document()
    except ValueError as exc:
        raise BrowserToolError(str(exc), tool=tool_name) from exc
    except (PlaywrightError, RuntimeError) as exc:
        raise BrowserToolError(
            "Unable to access browser page",
            tool=tool_name,
        ) from exc
    if resolved_tab.url in {"", "about:blank"}:
        raise BrowserToolError("Navigate to a page first.", tool=tool_name)
    return browser, resolved_tab, document


async def get_tab(tool_name: str, *, tab: str) -> tuple[Browser, Tab]:
    """Resolve an agent tab ID against the current browser."""
    try:
        browser = await get_browser()
        resolved_tab = browser.get_tab(tab)
    except ValueError as exc:
        raise BrowserToolError(str(exc), tool=tool_name) from exc
    except (PlaywrightError, RuntimeError) as exc:
        raise BrowserToolError(
            "Unable to access browser tab",
            tool=tool_name,
        ) from exc
    return browser, resolved_tab


__all__ = ["get_document", "get_tab"]
