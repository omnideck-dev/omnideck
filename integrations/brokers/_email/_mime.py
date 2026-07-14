"""Provider-neutral MIME body selection and rendering."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import cast

import html2text

_MAX_MIME_DEPTH = 50
_DIRECTLY_RENDERABLE_TYPES = frozenset({"text/plain", "text/html", "text/markdown"})


@dataclass(frozen=True, slots=True)
class MimePart:
    """Normalized subset of a MIME part needed to render an email body."""

    content_type: str
    body: bytes | None = None
    body_loader: Callable[[], bytes] | None = field(default=None, repr=False, compare=False)
    charset: str | None = None
    disposition: str | None = None
    filename: str | None = None
    content_id: str | None = None
    related_start: str | None = None
    children: tuple[MimePart, ...] = ()


def render_email_body(root: MimePart) -> str:
    """Render the best readable representation of a normalized MIME tree.

    ``multipart/alternative`` children are ordered from least to most
    faithful, so the last supported non-empty representation wins. Mixed and
    unknown multipart subtypes contain independent parts and are rendered in
    order. Related multipart containers render only their designated root.
    """
    return (_render_part(root, depth=0) or "").strip()


def is_attachment(part: MimePart) -> bool:
    """Return whether ``part`` should be exposed as an attachment."""
    disposition = (part.disposition or "").casefold()
    if disposition == "attachment":
        return True
    return bool(part.filename and disposition != "inline")


def html_to_markdown(text: str) -> str:
    """Render an HTML email body as agent-readable Markdown.

    ``HTML2Text`` is intentionally constructed per call: parser instances are
    stateful, and Gmail requests may render concurrently in worker threads.
    """
    converter = html2text.HTML2Text()
    converter.body_width = 0
    converter.ignore_images = True
    converter.unicode_snob = True
    converter.protect_links = True
    converter.skip_internal_links = True
    return cast(str, converter.handle(text)).strip()


def _render_part(part: MimePart, *, depth: int) -> str | None:
    if depth > _MAX_MIME_DEPTH or is_attachment(part):
        return None

    content_type = part.content_type.casefold()
    if content_type == "multipart/alternative":
        for child in reversed(part.children):
            rendered = _render_part(child, depth=depth + 1)
            if rendered and rendered.strip():
                return rendered
        return None

    if content_type == "multipart/related":
        root = _related_root(part)
        if root is None:
            return None
        return _render_part(root, depth=depth + 1)

    if content_type.startswith("multipart/") or content_type == "message/rfc822":
        rendered_children = [
            rendered
            for child in part.children
            if (rendered := _render_part(child, depth=depth + 1)) and rendered.strip()
        ]
        return "\n\n".join(rendered_children) or None

    if content_type not in _DIRECTLY_RENDERABLE_TYPES:
        return None

    decoded = _decode_body(part)
    if not decoded.strip():
        return None
    if content_type == "text/html":
        return html_to_markdown(decoded) or None
    return decoded


def _related_root(part: MimePart) -> MimePart | None:
    wanted_content_id = _normalize_content_id(part.related_start)
    if wanted_content_id:
        for child in part.children:
            if _normalize_content_id(child.content_id) == wanted_content_id:
                return child
    return next((child for child in part.children if not is_attachment(child)), None)


def _normalize_content_id(value: str | None) -> str:
    return (value or "").strip().removeprefix("<").removesuffix(">")


def _decode_body(part: MimePart) -> str:
    raw = part.body
    if raw is None and part.body_loader is not None:
        raw = part.body_loader()
    raw = raw or b""
    charset = part.charset or "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")
