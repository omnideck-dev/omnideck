"""Select option from dropdown tool."""

from __future__ import annotations

import logging

from playwright.async_api import Error as PlaywrightError

from ._tool_context import get_document
from ._tool_support import format_action_result
from .core.exceptions import BrowserToolError

logger = logging.getLogger(__name__)


async def select_option(
    ref: str,
    value: str,
    wait_after_select_ms: int | None = None,
    *,
    tab: str,
) -> str:
    """Select an option from a ``<select>`` dropdown by visible text.

    Args:
        ref: Ref number from ``browse_page()`` output.
            Examples: ``"7"``, ``"12"``.
        value: Exact visible text of the option (case-sensitive).
            Example: ``"Price: Low to High"``.
        wait_after_select_ms: Optional ms to wait after selecting.
        tab: Stable tab ID to inspect — the ID shown in the document
            header (e.g. ``tab="3"``).

    Returns:
        Formatted string with action header and rendered document.

    Raises:
        BrowserToolError: If dropdown not found or option text doesn't match.
    """
    clean_ref = ref.strip()
    logger.info("Selecting option '%s' from dropdown ref %s", value, clean_ref)

    browser, resolved_tab, document = await get_document("select_option", tab=tab)

    try:
        resolution = await document.resolve_ref(clean_ref, tool_name="select_option")

        async def _perform_select() -> None:
            await document.select_option(
                resolution,
                value,
                wait_after_select_ms=wait_after_select_ms,
            )

        # Perform interaction and check for page changes
        browser_result = await browser.coordinate_action(
            _perform_select,
            source_tab=resolved_tab,
        )
        return await format_action_result(browser_result, tool_name="select_option", resolution=resolution)
    except BrowserToolError:
        raise
    except PlaywrightError as exc:
        logger.exception("Failed to select option '%s' from ref %s", value, clean_ref)
        msg = f"Failed to select option '{value}' from dropdown ref {clean_ref}"
        raise BrowserToolError(msg, tool="select_option") from exc


__all__ = ["select_option"]
