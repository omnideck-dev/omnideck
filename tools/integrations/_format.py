"""Shared plain-text formatters for the email integration tools.

The envelope and byte-size renderings are reused across the listing, search,
read, and attachment-download tools. Keeping them in one place means every
tool emits an identically-shaped line, so the agent can round-trip a UID or
quote a size between tools without re-parsing.
"""

from __future__ import annotations

from typing import Any


def format_envelope(header: dict[str, Any], integration_id: str) -> str:
    """Render one message header as ``- [uid] (integration) date  sender  —  subject``.

    The bracketed ``integration_id`` makes it visually impossible to copy a
    UID from one envelope into a tool call against a different integration:
    Gmail message IDs and IMAP UIDs are not interchangeable, and the
    latter only round-trips through the same integration it was fetched from.
    Missing sender/subject fall back to placeholders rather than dropping
    columns, so the layout stays uniform and every line remains parseable.
    """
    uid = header.get("uid", "?")
    date = header.get("date") or ""
    sender = header.get("from_") or "(no sender)"
    subject = header.get("subject") or "(no subject)"
    return f"- [{uid}] ({integration_id}) {date}  {sender}  —  {subject}"


def format_size(size: int) -> str:
    """Compact human-readable byte count: ``1.2KB`` / ``245KB`` / ``3.4MB``."""
    if size < 1024:
        return f"{size}B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size / (1024 * 1024):.1f}MB"
