"""Unit tests for the shared email-tool formatters.

``format_envelope`` and ``format_size`` are reused across the listing,
search, read, and attachment-download tools; these tests pin their contract
directly (the per-tool tests cover them indirectly via rendered output).
"""

from __future__ import annotations

import pytest

from tools.integrations._format import format_envelope, format_size


@pytest.mark.unit
def test_format_envelope_renders_uid_bracket_line() -> None:
    line = format_envelope(
        {"uid": "100", "date": "2026-04-25T09:00:00+00:00", "from_": "alice@x", "subject": "hi"},
        "email_acme",
    )
    assert line == "- [100] (email_acme) 2026-04-25T09:00:00+00:00  alice@x  —  hi"


@pytest.mark.unit
def test_format_envelope_substitutes_placeholders_for_missing_fields() -> None:
    """Missing from_/subject become placeholders and missing uid becomes ``?``
    so the column layout stays uniform and the line is still parseable."""
    assert format_envelope({}, "email_acme") == "- [?] (email_acme)   (no sender)  —  (no subject)"


@pytest.mark.unit
def test_format_envelope_tags_integration_to_disambiguate_uids() -> None:
    """The integration id is embedded in every line so the agent can't copy a
    UID from one envelope into a tool call against a different integration.

    Gmail message IDs and IMAP UIDs are not interchangeable: a Gmail hex id
    passed to the iCloud broker returns 404, and an iCloud numeric id
    passed to the Gmail broker returns 404. Without the tag, the model
    conflated UIDs across integrations in observed runs.
    """
    gmail = format_envelope(
        {"uid": "19eb23e6a2444dd7", "from_": "a@b.com", "subject": "x"},
        "google_workspace",
    )
    icloud = format_envelope(
        {"uid": "16976", "from_": "c@d.com", "subject": "y"},
        "icloud_larry",
    )
    # The (integration) tag must sit between the UID and the date column.
    assert "(google_workspace)" in gmail
    assert "(icloud_larry)" in icloud
    # A model reading the gmail line cannot see ``16976`` without also
    # seeing ``(google_workspace)``; same for iCloud.
    assert "19eb23e6a2444dd7" in gmail and "(google_workspace)" in gmail
    assert "16976" in icloud and "(icloud_larry)" in icloud


@pytest.mark.unit
@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (0, "0B"),
        (1023, "1023B"),
        (1024, "1.0KB"),  # exact KB boundary crosses out of the byte branch
        (245_120, "239.4KB"),
        (1024 * 1024 - 1, "1024.0KB"),  # last value before the MB boundary
        (1024 * 1024, "1.0MB"),
        (1_258_291, "1.2MB"),
    ],
)
def test_format_size_picks_unit_by_threshold(size: int, expected: str) -> None:
    assert format_size(size) == expected
