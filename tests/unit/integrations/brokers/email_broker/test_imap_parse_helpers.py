"""Unit tests for the pure parse helpers in ``email_broker._imap_client``.

These cover the message-byte-blob → typed-domain-object boundary: the FETCH
preamble splitter, the RFC 2047 header decoder, the Date-header normalizer,
and the multipart-body-to-text rendering. Everything here is offline and
doesn't touch IMAP — building inputs from `email.message.EmailMessage` keeps
each assertion focused on one parser concern at a time.
"""

from __future__ import annotations

from email.message import EmailMessage

import pytest

from integrations.brokers.email_broker._imap_client import (
    _collect_fetch_pairs,
    _decode_header,
    _extract_attachments,
    _extract_body_text,
    _normalize_date,
    _parse_header_hit,
)


# ── _collect_fetch_pairs ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_collect_fetch_pairs_extracts_uid_and_payload_for_each_hit() -> None:
    """A typical multi-message FETCH response yields one pair per message.

    imaplib emits each hit as a 2-tuple ``(preamble_with_UID, raw_bytes)``.
    The helper pulls the UID out of the preamble bytes and pairs it with the
    payload — the ``b")"`` closer between hits is ignored.
    """
    data = [
        (b"1 (UID 100 BODY[HEADER.FIELDS (FROM TO SUBJECT DATE)] {12}", b"From: a@b\n"),
        b")",
        (b"2 (UID 101 BODY[HEADER.FIELDS (FROM TO SUBJECT DATE)] {12}", b"From: c@d\n"),
        b")",
    ]
    assert _collect_fetch_pairs(data) == [
        ("100", b"From: a@b\n"),
        ("101", b"From: c@d\n"),
    ]


@pytest.mark.unit
def test_collect_fetch_pairs_skips_items_without_uid() -> None:
    """Preambles missing the UID token are dropped silently — those happen on
    odd server responses (e.g. NOOP-style untagged updates) and we don't want
    to pretend we have a real message there.
    """
    data = [
        (b"1 (FLAGS (\\Seen))", b"<no UID here>"),
        (b"2 (UID 42 BODY[...] {3}", b"hi\n"),
    ]
    assert _collect_fetch_pairs(data) == [("42", b"hi\n")]


@pytest.mark.unit
def test_collect_fetch_pairs_skips_non_tuple_entries() -> None:
    """Closing parens (``b")"``), ints, and stray strings shouldn't crash —
    they just aren't message hits.
    """
    data = [b")", "stray-str", 7, (b"1 (UID 1 BODY[...] {1}", b"x")]
    assert _collect_fetch_pairs(data) == [("1", b"x")]


@pytest.mark.unit
def test_collect_fetch_pairs_returns_empty_for_empty_input() -> None:
    """No hits → empty list (not None)."""
    assert _collect_fetch_pairs([]) == []


# ── _decode_header ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_decode_header_returns_empty_for_empty_input() -> None:
    """No header value → empty string, no exception."""
    assert _decode_header("") == ""


@pytest.mark.unit
def test_decode_header_passes_plain_ascii_unchanged() -> None:
    """ASCII headers don't carry RFC 2047 encoded-words, so they're returned
    verbatim modulo whitespace trimming.
    """
    assert _decode_header("Hello world") == "Hello world"


@pytest.mark.unit
def test_decode_header_decodes_rfc2047_base64_utf8() -> None:
    """``=?UTF-8?B?...?=`` is the wire form for non-ASCII subjects/from-names.

    The helper has to round-trip the base64 + utf-8 charset back into a unicode
    string, otherwise the agent would see garbled bytes for any non-English
    header.
    """
    # "Héllo" base64-encoded as UTF-8.
    encoded = "=?UTF-8?B?SMOpbGxv?="
    assert _decode_header(encoded) == "Héllo"


@pytest.mark.unit
def test_decode_header_decodes_rfc2047_quoted_printable() -> None:
    """Quoted-printable is the other RFC 2047 encoding the decoder must
    handle (used by some clients for short non-ASCII strings).
    """
    encoded = "=?UTF-8?Q?caf=C3=A9?="
    assert _decode_header(encoded) == "café"


@pytest.mark.unit
def test_decode_header_concatenates_mixed_segments() -> None:
    """Real-world subjects often mix plain ASCII and encoded-words. The
    decoder must concatenate them without losing the unencoded segments.
    """
    encoded = '"=?UTF-8?B?SsO8cmdlbg==?=" <jurgen@example.com>'
    out = _decode_header(encoded)
    assert "Jürgen" in out
    assert "<jurgen@example.com>" in out


@pytest.mark.unit
def test_decode_header_falls_back_to_utf8_for_unknown_charset() -> None:
    """A bogus charset label shouldn't throw — the helper falls back to
    utf-8 with ``errors="replace"`` so the caller always gets a string.
    """
    # Charset "x-bogus" doesn't exist; the bytes themselves are valid UTF-8.
    encoded = "=?x-bogus?B?aGVsbG8=?="
    assert _decode_header(encoded) == "hello"


# ── _normalize_date ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_normalize_date_returns_empty_for_empty_input() -> None:
    """No Date header → empty string."""
    assert _normalize_date("") == ""


@pytest.mark.unit
def test_normalize_date_converts_rfc2822_to_iso8601() -> None:
    """RFC 2822 ``Tue, 1 Apr 2026 09:30:00 -0400`` → ``2026-04-01T09:30:00-04:00``.

    Normalizing to ISO 8601 makes the value consistent across providers and
    sortable lexicographically, which is what the agent and frontend both want.
    """
    iso = _normalize_date("Tue, 1 Apr 2026 09:30:00 -0400")
    assert iso.startswith("2026-04-01T09:30:00")
    assert iso.endswith("-04:00")


@pytest.mark.unit
def test_normalize_date_returns_input_unchanged_when_unparseable() -> None:
    """Non-RFC dates (rare, but seen in spam) are returned as-is rather than
    discarded — better to show *something* than blank out the field.
    """
    weird = "definitely not a date"
    assert _normalize_date(weird) == weird



# ── _extract_body_text ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_extract_body_text_selects_last_supported_alternative() -> None:
    """The sender's last supported alternative is the preferred version."""
    msg = EmailMessage()
    msg.set_content("plain version")
    msg.add_alternative("<p>html version</p>", subtype="html")
    out = _extract_body_text(msg)
    assert "html version" in out
    assert "plain version" not in out


@pytest.mark.unit
def test_extract_body_text_falls_back_when_preferred_alternative_is_empty() -> None:
    """An empty preferred representation falls back to the previous one."""
    msg = EmailMessage()
    msg.set_content("plain fallback")
    msg.add_alternative("<html><body></body></html>", subtype="html")
    assert "plain fallback" in _extract_body_text(msg)


@pytest.mark.unit
def test_extract_body_text_ignores_attached_html() -> None:
    """An HTML document attachment must not be mistaken for the body."""
    msg = EmailMessage()
    msg.set_content("actual body")
    msg.add_attachment(
        b"<p>attached document</p>",
        maintype="text",
        subtype="html",
        filename="document.html",
    )
    out = _extract_body_text(msg)
    assert "actual body" in out
    assert "attached document" not in out


@pytest.mark.unit
def test_extract_body_text_falls_back_to_html_as_markdown() -> None:
    """HTML-only messages get rendered to Markdown rather than returning
    empty. Tags become structure (``**bold**``); URLs survive intact.
    """
    msg = EmailMessage()
    msg.set_content(
        '<p>Hello <b>world</b> — see <a href="https://example.com">site</a>.</p>',
        subtype="html",
    )
    out = _extract_body_text(msg)
    assert "Hello" in out
    assert "**world**" in out  # html2text marks bold as Markdown emphasis
    assert "[site](<https://example.com>)" in out


@pytest.mark.unit
def test_extract_body_text_returns_plaintext_for_single_part_text() -> None:
    """Non-multipart text/plain → its content unchanged (modulo trailing
    newline that ``EmailMessage`` adds).
    """
    msg = EmailMessage()
    msg.set_content("just some words")
    assert "just some words" in _extract_body_text(msg)


@pytest.mark.unit
def test_extract_body_text_renders_single_part_html_as_markdown() -> None:
    """Non-multipart text/html → Markdown via html2text — no raw tags leak."""
    msg = EmailMessage()
    msg.set_content("<div>tagged <i>content</i></div>", subtype="html")
    out = _extract_body_text(msg)
    assert "<" not in out
    assert "tagged" in out and "content" in out
    # Italic survives as Markdown emphasis.
    assert "_content_" in out or "*content*" in out


@pytest.mark.unit
def test_extract_body_text_returns_empty_for_multipart_with_no_text_parts() -> None:
    """A multipart message that's nothing but attachments shouldn't crash;
    we return empty text so the caller can render headers + ``(no text body)``.
    """
    msg = EmailMessage()
    msg.set_content("placeholder")  # gets replaced by add_attachment below
    # Replace single-part with a multipart that has only an attachment.
    msg = EmailMessage()
    msg.make_mixed()
    msg.add_attachment(b"\x00\x01\x02", maintype="application", subtype="octet-stream", filename="blob.bin")
    assert _extract_body_text(msg) == ""


@pytest.mark.unit
def test_extract_attachments_skips_explicitly_inline_resources() -> None:
    """Related images with filenames do not clutter the attachment list."""
    msg = EmailMessage()
    msg.make_related()
    image = EmailMessage()
    image.set_content(b"PNG", maintype="image", subtype="png", disposition="inline", filename="logo.png")
    msg.attach(image)
    assert _extract_attachments(msg) == []


@pytest.mark.unit
def test_extract_attachments_keeps_true_attachments() -> None:
    """Parts marked as attachments remain available for download."""
    msg = EmailMessage()
    msg.add_attachment(b"PDF", maintype="application", subtype="pdf", filename="invoice.pdf")
    attachments = _extract_attachments(msg)
    assert len(attachments) == 1
    assert attachments[0].filename == "invoice.pdf"
    assert attachments[0].mime_type == "application/pdf"


@pytest.mark.unit
def test_extract_attachments_decodes_payload_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Attachment classification reads headers without decoding the body."""
    msg = EmailMessage()
    msg.add_attachment(b"PDF", maintype="application", subtype="pdf", filename="invoice.pdf")
    attachment = next(msg.iter_attachments())
    original_get_payload = attachment.get_payload
    decode_calls = 0

    def counting_get_payload(index: int | None = None, *, decode: bool = False):  # noqa: ANN202
        nonlocal decode_calls
        if decode:
            decode_calls += 1
        return original_get_payload(index, decode=decode)

    monkeypatch.setattr(attachment, "get_payload", counting_get_payload)
    assert len(_extract_attachments(msg)) == 1
    assert decode_calls == 1


# ── _parse_header_hit ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_parse_header_hit_populates_envelope_fields() -> None:
    """End-to-end: raw header bytes from a FETCH response → ``MessageHeader``
    with from / to / subject / date filled, plus the uid + folder the caller
    passed in.
    """
    raw = (
        b"From: alice@example.com\r\n"
        b"To: bob@example.com\r\n"
        b"Subject: Hello\r\n"
        b"Date: Tue, 1 Apr 2026 09:30:00 -0400\r\n"
        b"\r\n"
    )
    header = _parse_header_hit(uid="42", raw=raw, folder="INBOX")
    assert header.uid == "42"
    assert header.folder == "INBOX"
    assert header.from_ == "alice@example.com"
    assert header.to == "bob@example.com"
    assert header.subject == "Hello"
    assert header.date.startswith("2026-04-01T09:30:00")


@pytest.mark.unit
def test_parse_header_hit_handles_missing_fields_gracefully() -> None:
    """Servers can return partial header sets; absent fields become empty
    strings rather than raising.
    """
    raw = b"Subject: only-subject\r\n\r\n"
    header = _parse_header_hit(uid="1", raw=raw, folder="Drafts")
    assert header.subject == "only-subject"
    assert header.from_ == ""
    assert header.to == ""
    assert header.date == ""


@pytest.mark.unit
def test_parse_header_hit_decodes_encoded_word_subject() -> None:
    """Subjects often arrive RFC 2047-encoded; ``_parse_header_hit`` must run
    them through ``_decode_header`` before populating the model.
    """
    raw = (
        b"Subject: =?UTF-8?B?SMOpbGxv?=\r\n"
        b"\r\n"
    )
    header = _parse_header_hit(uid="9", raw=raw, folder="INBOX")
    assert header.subject == "Héllo"
