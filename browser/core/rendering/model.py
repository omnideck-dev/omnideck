"""Immutable output produced from a selected browser document."""

from __future__ import annotations

from dataclasses import dataclass

from browser.core.settling import SettleTimings


@dataclass(frozen=True, slots=True)
class RenderedDocument:
    """Agent-readable data rendered from one selected document.

    Attributes:
        title: Page title.
        url: Final URL after any redirects.
        status_code: HTTP status code, if navigation supplied one.
        content: Annotated text containing content and interaction refs.
        viewport: Current viewport and scroll state.
        truncated: Whether the character budget truncated the content.
        modal_open: Whether a modal currently makes background controls unavailable.
        settle_timings: Timings collected while waiting for the document to settle.
        dom_walk_ms: Time spent walking the DOM in the browser, in milliseconds.
        render_ms: Time spent converting DOM nodes into annotated text, in milliseconds.
        node_count: Number of structured nodes emitted by the DOM walk.
    """

    title: str
    url: str
    status_code: int | None
    content: str
    viewport: dict[str, int] | None
    truncated: bool
    modal_open: bool = False
    settle_timings: SettleTimings | None = None
    dom_walk_ms: float = 0.0
    render_ms: float = 0.0
    node_count: int = 0


__all__ = ["RenderedDocument"]
