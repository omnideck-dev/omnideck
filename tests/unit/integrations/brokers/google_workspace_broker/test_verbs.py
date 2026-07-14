"""Unit tests for Google Workspace broker verb helpers."""

from __future__ import annotations

import base64

import pytest

from integrations.brokers.google_workspace_broker._gmail_client import (
    _decode_base64url,
    _extract_text_body,
    _list_attachments,
)
from integrations.brokers.google_workspace_broker._verbs import _flatten_contact, _flatten_event


@pytest.mark.unit
def test_flatten_timed_event() -> None:
    """Timed events use ``start.dateTime``."""
    raw = {
        "id": "abc123",
        "summary": "Standup",
        "start": {"dateTime": "2026-05-05T09:00:00-04:00", "timeZone": "America/New_York"},
        "end": {"dateTime": "2026-05-05T09:15:00-04:00", "timeZone": "America/New_York"},
        "location": "Zoom",
    }
    assert _flatten_event(raw) == {
        "uid": "abc123",
        "summary": "Standup",
        "start": "2026-05-05T09:00:00-04:00",
        "end": "2026-05-05T09:15:00-04:00",
        "location": "Zoom",
    }


@pytest.mark.unit
def test_flatten_all_day_event() -> None:
    """All-day events have ``start.date`` instead of ``start.dateTime``."""
    raw = {
        "id": "def456",
        "summary": "Company Holiday",
        "start": {"date": "2026-05-25"},
        "end": {"date": "2026-05-26"},
    }
    assert _flatten_event(raw) == {
        "uid": "def456",
        "summary": "Company Holiday",
        "start": "2026-05-25",
        "end": "2026-05-26",
        "location": "",
    }


@pytest.mark.unit
def test_flatten_minimal_event() -> None:
    """An event missing most fields still produces a complete dict."""
    assert _flatten_event({"id": "x"}) == {
        "uid": "x",
        "summary": "",
        "start": "",
        "end": "",
        "location": "",
    }


@pytest.mark.unit
def test_flatten_prefers_datetime_over_date() -> None:
    """If both ``dateTime`` and ``date`` are present, ``dateTime`` wins."""
    raw = {
        "id": "both",
        "summary": "Edge case",
        "start": {"dateTime": "2026-05-05T10:00:00Z", "date": "2026-05-05"},
        "end": {"dateTime": "2026-05-05T11:00:00Z", "date": "2026-05-05"},
    }
    flat = _flatten_event(raw)
    assert flat["start"] == "2026-05-05T10:00:00Z"
    assert flat["end"] == "2026-05-05T11:00:00Z"


# ── Gmail helpers ──────────────────────────────────────────────────────────


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


@pytest.mark.unit
def test_decode_base64url_accepts_unpadded_gmail_data() -> None:
    assert _decode_base64url("SGVsbG8") == b"Hello"


@pytest.mark.unit
def test_decode_base64url_rejects_invalid_data() -> None:
    assert _decode_base64url("not valid ***") is None


@pytest.mark.unit
def test_extract_text_body_simple_text_plain() -> None:
    """Simple message with text/plain at the top level."""
    payload = {
        "mimeType": "text/plain",
        "body": {"data": _b64url("Hello world")},
    }
    assert _extract_text_body(payload) == "Hello world"


@pytest.mark.unit
def test_extract_text_body_multipart() -> None:
    """Multipart alternative — selects the sender's preferred HTML part."""
    payload = {
        "mimeType": "multipart/alternative",
        "body": {"size": 0},
        "parts": [
            {
                "mimeType": "text/plain",
                "body": {"data": _b64url("Plain version")},
            },
            {
                "mimeType": "text/html",
                "body": {"data": _b64url("<p>HTML version</p>")},
            },
        ],
    }
    assert _extract_text_body(payload) == "HTML version"


@pytest.mark.unit
def test_extract_text_body_html_only() -> None:
    """HTML-only Gmail messages are converted to Markdown."""
    payload = {
        "mimeType": "text/html",
        "headers": [{"name": "Content-Type", "value": "text/html; charset=utf-8"}],
        "body": {"data": _b64url("<p>Hello <strong>world</strong>.</p>")},
    }
    assert _extract_text_body(payload) == "Hello **world**."


@pytest.mark.unit
def test_extract_text_body_loads_large_html_part_by_attachment_id() -> None:
    """Gmail may store a large inline body behind ``attachmentId``."""
    payload = {
        "mimeType": "text/html",
        "body": {"attachmentId": "body_part", "size": 4096},
    }
    requested: list[str] = []

    def load_body(attachment_id: str) -> bytes:
        requested.append(attachment_id)
        return b"<p>Large <strong>receipt</strong></p>"

    assert _extract_text_body(payload, body_loader=load_body) == "Large **receipt**"
    assert requested == ["body_part"]


@pytest.mark.unit
def test_extract_text_body_does_not_load_unselected_alternative() -> None:
    """Lazy Gmail body loads fetch only the selected preferred alternative."""
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/plain", "body": {"attachmentId": "plain_part"}},
            {"mimeType": "text/html", "body": {"attachmentId": "html_part"}},
        ],
    }
    requested: list[str] = []

    def load_body(attachment_id: str) -> bytes:
        requested.append(attachment_id)
        return b"<p>Preferred HTML</p>" if attachment_id == "html_part" else b"Plain"

    assert _extract_text_body(payload, body_loader=load_body) == "Preferred HTML"
    assert requested == ["html_part"]


@pytest.mark.unit
def test_extract_text_body_ignores_attached_html() -> None:
    """An attached HTML document is not selected as the message body."""
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64url("Actual body")}},
            {
                "mimeType": "text/html",
                "filename": "document.html",
                "headers": [
                    {
                        "name": "Content-Disposition",
                        "value": 'attachment; filename="document.html"',
                    },
                ],
                "body": {"data": _b64url("<p>Attached document</p>")},
            },
        ],
    }
    assert _extract_text_body(payload) == "Actual body"


@pytest.mark.unit
def test_extract_text_body_nested_multipart() -> None:
    """Deeply nested MIME structure — text/plain inside multipart/mixed."""
    payload = {
        "mimeType": "multipart/mixed",
        "body": {"size": 0},
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "body": {"size": 0},
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": _b64url("Nested body")},
                    },
                ],
            },
            {
                "mimeType": "application/pdf",
                "filename": "report.pdf",
                "body": {"attachmentId": "att1", "size": 1024},
            },
        ],
    }
    assert _extract_text_body(payload) == "Nested body"


@pytest.mark.unit
def test_extract_text_body_empty_payload() -> None:
    assert _extract_text_body({}) == ""


@pytest.mark.unit
def test_list_attachments_collects_from_parts() -> None:
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {
                "mimeType": "text/plain",
                "body": {"data": _b64url("body"), "size": 4},
            },
            {
                "mimeType": "application/pdf",
                "filename": "report.pdf",
                "body": {"attachmentId": "att_abc", "size": 2048},
            },
            {
                "mimeType": "image/png",
                "filename": "chart.png",
                "body": {"attachmentId": "att_def", "size": 512},
            },
        ],
    }
    atts = _list_attachments("msg1", payload)
    assert len(atts) == 2
    assert atts[0] == {
        "id": "att_abc",
        "filename": "report.pdf",
        "mime_type": "application/pdf",
        "size": 2048,
    }
    assert atts[1] == {
        "id": "att_def",
        "filename": "chart.png",
        "mime_type": "image/png",
        "size": 512,
    }


@pytest.mark.unit
def test_list_attachments_skips_parts_without_filename() -> None:
    """Inline parts (no filename) are not listed as downloadable attachments."""
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {
                "mimeType": "image/png",
                "body": {"attachmentId": "inline_img", "size": 100},
            },
        ],
    }
    assert _list_attachments("msg1", payload) == []


@pytest.mark.unit
def test_list_attachments_skips_explicitly_inline_resources() -> None:
    """Related images with filenames do not clutter the attachment list."""
    payload = {
        "mimeType": "multipart/related",
        "parts": [
            {
                "mimeType": "image/png",
                "filename": "logo.png",
                "headers": [{"name": "Content-Disposition", "value": 'inline; filename="logo.png"'}],
                "body": {"attachmentId": "inline_img", "size": 100},
            },
        ],
    }
    assert _list_attachments("msg1", payload) == []


@pytest.mark.unit
def test_list_attachments_empty() -> None:
    assert _list_attachments("msg1", {"mimeType": "text/plain"}) == []


# ── Contacts helpers ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_flatten_contact_full() -> None:
    person = {
        "names": [{"displayName": "Alice Smith"}],
        "emailAddresses": [{"value": "alice@example.com"}],
        "phoneNumbers": [{"value": "+1-555-0100"}],
        "organizations": [{"name": "Acme Corp", "title": "CEO"}],
    }
    assert _flatten_contact(person) == {
        "name": "Alice Smith",
        "emails": ["alice@example.com"],
        "phones": ["+1-555-0100"],
        "organization": "Acme Corp",
        "title": "CEO",
    }


@pytest.mark.unit
def test_flatten_contact_multiple_emails_and_phones() -> None:
    person = {
        "names": [{"displayName": "Bob"}],
        "emailAddresses": [{"value": "bob@work.com"}, {"value": "bob@home.com"}],
        "phoneNumbers": [{"value": "+1-555-0001"}, {"value": "+1-555-0002"}],
        "organizations": [],
    }
    flat = _flatten_contact(person)
    assert flat["emails"] == ["bob@work.com", "bob@home.com"]
    assert flat["phones"] == ["+1-555-0001", "+1-555-0002"]


@pytest.mark.unit
def test_flatten_contact_minimal() -> None:
    assert _flatten_contact({}) == {
        "name": "",
        "emails": [],
        "phones": [],
        "organization": "",
        "title": "",
    }
