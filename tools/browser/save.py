"""Agent tool for saving a tab's content to the virtual computer."""

from __future__ import annotations

import logging
from pathlib import Path

from browser.core.exceptions import BrowserToolError
from browser.core.formatting import format_save_result
from browser.core.markdown import html_to_markdown
from config import load_config
from tools.browser._tool_context import get_document

logger = logging.getLogger(__name__)


async def save_page_content(filename: str, *, tab: str) -> str:
    """Save the current page as markdown to /home/omnideck/<filename>.

    Use when ``read_page()`` output is truncated and you need the full page
    for processing with ``run_bash_cmd()`` (e.g. grep, cat).

    Args:
        filename: Plain filename without directories (e.g. ``"page.md"``).
        tab: Stable tab ID shown in browser tool output.

    Returns:
        Formatted string with filename, container path, and size.

    Raises:
        BrowserToolError: If the tab cannot be read or the file cannot be saved.
    """
    _, resolved_tab, document = await get_document("save_page_content", tab=tab)

    # Reject paths with directory separators to keep files in the home dir
    if "/" in filename or "\\" in filename:
        msg = "filename must be a plain name without directory separators."
        raise BrowserToolError(msg, tool="save_page_content")

    config = load_config()
    home_dir = Path(config.virtual_computer.home_dir)

    dest = home_dir / filename

    logger.info("Saving page content from %s to %s", resolved_tab.url, dest)

    try:
        raw_html = await document.content()
        content = html_to_markdown(raw_html)
        home_dir.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        size = dest.stat().st_size

        logger.info("Saved %d bytes to %s", size, dest)
        return format_save_result(
            filename=filename,
            path=str(dest),
            size_bytes=size,
        )
    except BrowserToolError:
        raise
    except Exception as exc:
        logger.exception("Failed to save page content to %s", dest)
        raise BrowserToolError(str(exc), tool="save_page_content") from exc


__all__ = ["save_page_content"]
