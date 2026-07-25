"""Agent tool for browsing a tab's interactive, parsed content.

Returns rendered document content with interactive elements,
annotated with ``[ref] [role] name`` markers.  Pass the ref number to
``click()``, ``fill_field()``, and other interaction tools.
"""

from __future__ import annotations

import logging

from tools.browser._tool_context import get_document
from tools.browser.core.exceptions import BrowserToolError
from tools.browser.core.formatting import format_rendered_document
from tools.browser.events import emit_screenshot_after

logger = logging.getLogger(__name__)


@emit_screenshot_after
async def browse_page(
    scope: str | None = None,
    full_page: bool = False,
    *,
    tab: str,
) -> str:
    """See interactive elements on the current page with ref numbers.

    Use this when you need to INTERACT: find buttons, links, forms, and get
    ref numbers for ``click()``, ``fill_field()``, etc.  For reading text
    content, use ``read_page()`` instead.  After click/fill/scroll, the
    rendered document is returned automatically — only call ``browse_page()`` to
    re-examine without acting.

    Output format — each element shown as ``[ref] [role] name``::

        [3] [searchbox] Search Amazon
        [4] [link] Sony WH-1000XM5
        $348.00
        [5] [button] Add to Cart

    Pass the ref number to interaction tools::

        click("5")
        fill_field("3", "laptop")

    Args:
        scope: Narrow to a section by heading or landmark text.  Example:
            ``browse_page(scope="Results")`` to skip nav and sidebars.
            Respects viewport clipping — combine with ``full_page=True``
            for off-screen sections.
        full_page: Show all elements, not just the current viewport.
            Useful for finding elements without scrolling.  Long pages
            may be truncated.
        tab: Stable tab ID to inspect — the ID shown in the document
            header (e.g. ``tab="3"``).

    Returns:
        Formatted string with page header, viewport info, and annotated content.

    Raises:
        BrowserToolError: If there is no open page.
    """
    _browser, resolved_tab, _document = await get_document("browse_page", tab=tab)

    try:
        rendered = await resolved_tab.render_document(
            settle=False,
            scope=scope,
            full_page=full_page,
        )
        return format_rendered_document(rendered, tab_id=resolved_tab.id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Failed to render annotated document")
        raise BrowserToolError("Failed to render page", tool="browse_page") from exc


__all__ = ["browse_page"]
