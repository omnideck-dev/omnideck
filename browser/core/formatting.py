"""Format rendered browser documents and tool results for the agent."""

from __future__ import annotations

import json
from typing import Any

from browser.core.rendering import RenderedDocument

_MODAL_NOTICE = "[Modal dialog open — background controls are unavailable]"


def format_page_header(
    *,
    title: str,
    url: str,
    status: str | None = None,
    tab_id: int | None = None,
) -> str:
    """Build the shared ``[Page: title | url | ...]`` line.

    This is the one part of a rendered document every browser tool formats the same
    way, so the agent always sees the same "what page am I on" line.

    ``status`` is the already-rendered status text. ``None`` drops the segment
    entirely; an empty string keeps an empty slot, the shape a status-less document
    has always shown. ``tab_id`` adds ``tab=N`` when present.
    """
    parts = [title, url]
    if status is not None:
        parts.append(status)
    if tab_id is not None:
        parts.append(f"tab={tab_id}")
    return f"[Page: {' | '.join(parts)}]"


def format_rendered_document(
    rendered: RenderedDocument,
    *,
    tab_id: int | None = None,
) -> str:
    """Format one rendered document using the stable agent output shape.

    Args:
        rendered: Complete document rendering to format.
        tab_id: Stable ID for the tab represented by the document. When set, the
            header carries ``tab=N`` so the agent can echo it back on
            subsequent calls.

    Returns:
        Formatted string with header and content.
    """
    trunc = " | truncated" if rendered.truncated else ""

    header = format_page_header(
        title=rendered.title,
        url=rendered.url,
        status="" if rendered.status_code is None else str(rendered.status_code),
        tab_id=tab_id,
    )
    if rendered.viewport is None:
        vp_line = "[Viewport: unavailable]"
    else:
        scroll_top = rendered.viewport.get("scroll_top", 0)
        vh = rendered.viewport.get("viewport_height", 0)
        doc_h = rendered.viewport.get("document_height", 0)
        vp_line = f"[Viewport: {scroll_top}-{scroll_top + vh} of {doc_h}px{trunc}]"

    content = rendered.content
    if rendered.modal_open:
        content = f"{_MODAL_NOTICE}\n{content}" if content else _MODAL_NOTICE

    return f"{header}\n{vp_line}\n\n{content}"


def format_javascript_result(
    *,
    success: bool,
    result: Any | None = None,
    console_output: list[str] | None = None,
    error: str | None = None,
) -> str:
    r"""Format a JavaScript execution result for the LLM.

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
    "format_rendered_document",
    "format_save_result",
]
