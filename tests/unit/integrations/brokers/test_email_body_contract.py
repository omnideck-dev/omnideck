"""Cross-provider contracts for MIME body selection."""

from __future__ import annotations

import base64
import email

import pytest

from integrations.brokers.email_broker._imap_client import _extract_body_text
from integrations.brokers.google_workspace_broker._gmail_client import _extract_text_body


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode()


def _imap_body(raw: bytes) -> str:
    return _extract_body_text(email.message_from_bytes(raw))


def _assert_same_body(raw: bytes, gmail_payload: dict[str, object], expected: str) -> None:
    assert _imap_body(raw) == expected
    assert _extract_text_body(gmail_payload) == expected


@pytest.mark.unit
def test_both_backends_select_html_from_multipart_alternative() -> None:
    raw = (
        b'Content-Type: multipart/alternative; boundary="alt"\r\n\r\n'
        b"--alt\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nPlain receipt\r\n"
        b"--alt\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        b"<p><strong>Rich receipt</strong></p>\r\n--alt--\r\n"
    )
    gmail = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64(b"Plain receipt")}},
            {
                "mimeType": "text/html",
                "headers": [{"name": "Content-Type", "value": "text/html; charset=utf-8"}],
                "body": {"data": _b64(b"<p><strong>Rich receipt</strong></p>")},
            },
        ],
    }
    _assert_same_body(raw, gmail, "**Rich receipt**")


@pytest.mark.unit
def test_both_backends_render_mixed_inline_parts_and_skip_attachment() -> None:
    raw = (
        b'Content-Type: multipart/mixed; boundary="mixed"\r\n\r\n'
        b"--mixed\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nFirst section\r\n"
        b"--mixed\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<p>Second section</p>\r\n"
        b"--mixed\r\nContent-Type: text/html; charset=utf-8\r\n"
        b'Content-Disposition: attachment; filename="document.html"\r\n\r\n'
        b"<p>Attached document</p>\r\n--mixed--\r\n"
    )
    gmail = {
        "mimeType": "multipart/mixed",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64(b"First section")}},
            {"mimeType": "text/html", "body": {"data": _b64(b"<p>Second section</p>")}},
            {
                "mimeType": "text/html",
                "filename": "document.html",
                "headers": [{"name": "Content-Disposition", "value": "attachment"}],
                "body": {"data": _b64(b"<p>Attached document</p>")},
            },
        ],
    }
    _assert_same_body(raw, gmail, "First section\n\nSecond section")


@pytest.mark.unit
def test_both_backends_honor_multipart_related_start_parameter() -> None:
    raw = (
        b'Content-Type: multipart/related; boundary="related"; start="<body>"\r\n\r\n'
        b"--related\r\nContent-Type: image/png\r\nContent-ID: <logo>\r\n\r\nPNG\r\n"
        b"--related\r\nContent-Type: text/html; charset=utf-8\r\nContent-ID: <body>\r\n\r\n"
        b"<p>Related body</p>\r\n--related--\r\n"
    )
    gmail = {
        "mimeType": "multipart/related",
        "headers": [
            {
                "name": "Content-Type",
                "value": 'multipart/related; boundary="related"; start="<body>"',
            },
        ],
        "parts": [
            {
                "mimeType": "image/png",
                "headers": [{"name": "Content-ID", "value": "<logo>"}],
                "body": {"data": _b64(b"PNG")},
            },
            {
                "mimeType": "text/html",
                "headers": [{"name": "Content-ID", "value": "<body>"}],
                "body": {"data": _b64(b"<p>Related body</p>")},
            },
        ],
    }
    _assert_same_body(raw, gmail, "Related body")


@pytest.mark.unit
def test_both_backends_decode_declared_charset() -> None:
    text = "café receipt"
    encoded = text.encode("iso-8859-1")
    raw = b"Content-Type: text/plain; charset=iso-8859-1\r\n\r\n" + encoded
    gmail = {
        "mimeType": "text/plain",
        "headers": [{"name": "Content-Type", "value": "text/plain; charset=iso-8859-1"}],
        "body": {"data": _b64(encoded)},
    }
    _assert_same_body(raw, gmail, text)
