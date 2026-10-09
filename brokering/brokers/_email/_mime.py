"""Provider-neutral MIME body selection and rendering."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import cast

import html2text

_MAX_MIME_DEPTH = 50
_DIRECTLY_RENDERABLE_TYPES = frozenset({"text/plain", "text/html", "text/markdown"})


class BodyUnavailableError(Exception):
    """The selected representation could not be loaded or decoded."""


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


def is_attachment(disposition: str | None, filename: str | None) -> bool:
    """Classify a part as an attachment using MIME metadata only."""
    normalized_disposition = (disposition or "").casefold()
    if normalized_disposition == "attachment":
        return True
    return bool(filename and normalized_disposition != "inline")


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
    if depth > _MAX_MIME_DEPTH or is_attachment(part.disposition, part.filename):
        return None

    content_type = part.content_type.casefold()
    if content_type == "multipart/alternative":
        for child in reversed(part.children):
            rendered = _render_part(child, depth=depth + 1)
            if rendered and rendered.strip():
                return rendered
        return None

    if content_type == "multipart/related":
        for candidate in _related_candidates(part):
            rendered = _render_part(candidate, depth=depth + 1)
            if rendered and rendered.strip():
                return rendered
        return None

    if content_type.startswith("multipart/") or content_type == "message/rfc822":
        rendered_children = [
            rendered
            for child in part.children
            if (rendered := _render_part(child, depth=depth + 1)) and rendered.strip()
        ]
        return "\n\n".join(rendered_children) or None

    if content_type not in _DIRECTLY_RENDERABLE_TYPES:
        return None

    try:
        decoded = _decode_body(part)
    except BodyUnavailableError:
        return None
    if not decoded.strip():
        return None
    if content_type == "text/html":
        return html_to_markdown(decoded) or None
    return decoded


def _related_candidates(part: MimePart) -> tuple[MimePart, ...]:
    """Return the declared related root followed by pragmatic fallbacks.

    MIME defines the first child as the root when ``start`` is absent. Some
    malformed real-world messages put an inline image first, so if the root is
    not renderable the remaining inline children are tried in wire order.
    """
    wanted_content_id = _normalize_content_id(part.related_start)
    root: MimePart | None = None
    if wanted_content_id:
        for child in part.children:
            if _normalize_content_id(child.content_id) == wanted_content_id:
                root = child
                break
    if root is None:
        root = next(
            (
                child
                for child in part.children
                if not is_attachment(child.disposition, child.filename)
            ),
            None,
        )
    if root is None:
        return ()
    fallbacks = tuple(
        child
        for child in part.children
        if child is not root and not is_attachment(child.disposition, child.filename)
    )
    return (root, *fallbacks)


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
