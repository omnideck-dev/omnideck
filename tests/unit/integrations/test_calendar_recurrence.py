"""Tests for shared calendar recurrence validation."""

from __future__ import annotations

import pytest

from integrations.calendar_recurrence import normalize_recurrence_rule, normalize_time_zone


def test_recurrence_rule_accepts_prefix_and_canonicalizes() -> None:
    """RRULE input is normalized to one provider-neutral value."""
    assert normalize_recurrence_rule(
        "RRULE:FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4",
    ) == "FREQ=WEEKLY;COUNT=4;BYDAY=MO,WE"


@pytest.mark.parametrize("value", [None, "", "  "])
def test_empty_recurrence_is_a_one_time_event(value: str | None) -> None:
    """Omitted recurrence remains distinguishable from a series."""
    assert normalize_recurrence_rule(value) is None


@pytest.mark.parametrize("value", ["COUNT=4", "FREQ=NOPE", "FREQ=WEEKLY\nSUMMARY:x"])
def test_invalid_recurrence_is_rejected(value: str) -> None:
    """Malformed rules and property injection fail before provider calls."""
    with pytest.raises(ValueError, match="recurrence_rule"):
        normalize_recurrence_rule(value)


def test_time_zone_requires_iana_name() -> None:
    """IANA zones pass while arbitrary labels fail."""
    assert normalize_time_zone(" America/Chicago ") == "America/Chicago"
    with pytest.raises(ValueError, match="IANA"):
        normalize_time_zone("Central Time")
