"""Unit tests for provider-neutral MIME selection and rendering."""

from __future__ import annotations

import pytest

from integrations.brokers._email._mime import (
    BodyUnavailableError,
    MimePart,
    html_to_markdown,
    is_attachment,
    render_email_body,
)


@pytest.mark.unit
def test_html_to_markdown_preserves_link_text_and_url() -> None:
    html = '<p>Click <a href="https://example.com/confirm">here</a> to confirm.</p>'
    assert "[here](<https://example.com/confirm>)" in html_to_markdown(html)


@pytest.mark.unit
def test_html_to_markdown_drops_style_and_script_content() -> None:
    html = (
        "<html><head><style>.x { color: red; }</style></head>"
        "<body><script>alert('hi')</script><p>Real body.</p></body></html>"
    )
    rendered = html_to_markdown(html)
    assert "Real body." in rendered
    assert "color: red" not in rendered
    assert "alert" not in rendered


@pytest.mark.unit
def test_html_to_markdown_decodes_html_entities() -> None:
    rendered = html_to_markdown("<p>Q&amp;A &mdash; tips &nbsp;and tricks</p>")
    assert "Q&A" in rendered
    assert "&amp;" not in rendered
    assert "&mdash;" not in rendered


@pytest.mark.unit
def test_html_to_markdown_renders_lists_as_markdown() -> None:
    rendered = html_to_markdown("<ul><li>first</li><li>second</li><li>third</li></ul>")
    assert "* first" in rendered
    assert "* second" in rendered
    assert "* third" in rendered


@pytest.mark.unit
def test_html_to_markdown_returns_empty_for_empty_input() -> None:
    assert html_to_markdown("") == ""


@pytest.mark.unit
def test_renderer_decodes_declared_charset() -> None:
    part = MimePart(content_type="text/plain", body="héllo world".encode(), charset="utf-8")
    assert render_email_body(part) == "héllo world"


@pytest.mark.unit
def test_renderer_falls_back_to_utf8_for_unknown_charset() -> None:
    part = MimePart(content_type="text/plain", body=b"plain ascii", charset="x-bogus")
    assert render_email_body(part) == "plain ascii"


@pytest.mark.unit
def test_unavailable_preferred_body_falls_back_to_earlier_alternative() -> None:
    def unavailable() -> bytes:
        raise BodyUnavailableError("corrupt body data")

    root = MimePart(
        content_type="multipart/alternative",
        children=(
            MimePart(content_type="text/plain", body=b"Plain fallback"),
            MimePart(content_type="text/html", body_loader=unavailable),
        ),
    )
    assert render_email_body(root) == "Plain fallback"


@pytest.mark.unit
def test_unexpected_body_loader_error_propagates() -> None:
    class ProviderError(Exception):
        pass

    def fail() -> bytes:
        raise ProviderError("network failed")

    part = MimePart(content_type="text/plain", body_loader=fail)
    with pytest.raises(ProviderError, match="network failed"):
        render_email_body(part)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("disposition", "filename", "expected"),
    [
        ("attachment", None, True),
        (None, "invoice.pdf", True),
        ("inline", "logo.png", False),
        (None, None, False),
    ],
)
def test_attachment_classification_uses_metadata_only(
    disposition: str | None,
    filename: str | None,
    expected: bool,
) -> None:
    assert is_attachment(disposition, filename) is expected
