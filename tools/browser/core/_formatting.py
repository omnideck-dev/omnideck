"""String formatting for browser tool results.

Converts internal PageView data into plain-text strings for LLM consumption.
All browser tools that return page content use ``format_page_view`` so the
LLM always sees a consistent format.
"""

from __future__ import annotations

import json
from typing import Any


def format_page_header(
    *,
    title: str,
    url: str,
    status: str | None = None,
    tab_id: int | None = None,
) -> str:
    """Build the shared ``[Page: title | url | ...]`` line.

    This is the one part of a page view every browser tool renders the same
    way, so the agent always sees the same "what page am I on" line.

    ``status`` is the already-rendered status text. ``None`` drops the segment
    entirely; an empty string keeps an empty slot, the shape a status-less view
    has always shown. ``tab_id`` adds ``tab=N`` when present.
    """
    parts = [title, url]
    if status is not None:
        parts.append(status)
    if tab_id is not None:
        parts.append(f"tab={tab_id}")
    return f"[Page: {' | '.join(parts)}]"


def format_page_view(
    *,
    title: str,
    url: str,
    status_code: int | None,
    viewport: dict[str, int] | None,
    content: str,
    truncated: bool,
    downloaded_file: Any | None = None,
    tab_id: int | None = None,
) -> str:
    """Format a page view as a plain-text string for the LLM.

    Args:
        title: Page title.
        url: Final URL after redirects.
        status_code: HTTP status code or None.
        viewport: Viewport/scroll state dict.
        content: Annotated page content.
        truncated: Whether content was truncated.
        downloaded_file: Optional DownloadInfo from file detection.
        tab_id: Stable tab ID for the snapshot's tab.  When set, the
            header carries ``tab=N`` so the agent can echo it back on
            subsequent calls.

    Returns:
        Formatted string with header and content.
    """
    if downloaded_file is not None:
        from tools.browser.core._file_detection import format_download_message

        return format_download_message(downloaded_file)

    trunc = " | truncated" if truncated else ""

    header = format_page_header(
        title=title,
        url=url,
        status="" if status_code is None else str(status_code),
        tab_id=tab_id,
    )
    if viewport is None:
        vp_line = "[Viewport: unavailable]"
    else:
        scroll_top = viewport.get("scroll_top", 0)
        vh = viewport.get("viewport_height", 0)
        doc_h = viewport.get("document_height", 0)
        vp_line = f"[Viewport: {scroll_top}-{scroll_top + vh} of {doc_h}px{trunc}]"

    return f"{header}\n{vp_line}\n\n{content}"


def format_javascript_result(
    *,
    success: bool,
    result: Any | None = None,
    console_output: list[str] | None = None,
    error: str | None = None,
) -> str:
    """Format a JavaScript execution result for the LLM.

    Args:
        success: Whether the execution succeeded.
        result: The return value (omitted when None).
        console_output: Captured console lines (omitted when empty).
        error: Error message on failure (omitted when None).

    Returns:
        Formatted string like ``[JavaScript: success]\\nResult: ...``.
    """
    status = "success" if success else "error"
    parts = [f"[JavaScript: {status}]"]

    if error is not None:
        parts.append(f"Error: {error}")
    elif result is not None:
        try:
            serialized = json.dumps(result)
        except (TypeError, ValueError):
            serialized = repr(result)
        parts.append(f"Result: {serialized}")

    if console_output:
        parts.append(f"Console: {' | '.join(console_output)}")

    return "\n".join(parts)


def format_save_result(
    *,
    filename: str,
    path: str,
    size_bytes: int,
) -> str:
    """Format a save-content result for the LLM.

    Args:
        filename: The filename that was saved.
        path: Absolute path where the file was saved.
        size_bytes: File size in bytes.

    Returns:
        Formatted string like ``[Saved: page.md | /home/omnideck/page.md | 12345 bytes]``.
    """
    return f"[Saved: {filename} | {path} | {size_bytes} bytes]"


__all__ = [
    "format_javascript_result",
    "format_page_header",
    "format_page_view",
    "format_save_result",
]
