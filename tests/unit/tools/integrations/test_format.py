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
    )
    assert line == "- [100] 2026-04-25T09:00:00+00:00  alice@x  —  hi"


@pytest.mark.unit
def test_format_envelope_substitutes_placeholders_for_missing_fields() -> None:
    """Missing from_/subject become placeholders and missing uid becomes ``?``
    so the column layout stays uniform and the line is still parseable."""
    assert format_envelope({}) == "- [?]   (no sender)  —  (no subject)"


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
