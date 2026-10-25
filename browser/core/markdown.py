"""Convert browser HTML into Markdown."""

from __future__ import annotations

import html2text


def html_to_markdown(html: str) -> str:
    """Convert HTML to markdown."""
    converter = html2text.HTML2Text()
    converter.ignore_images = True
    converter.ignore_emphasis = False
    converter.body_width = 0
    converter.protect_links = True
    converter.unicode_snob = True
    return converter.handle(html)


__all__ = ["html_to_markdown"]
