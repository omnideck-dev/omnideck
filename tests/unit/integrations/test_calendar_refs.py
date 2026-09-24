"""Tests for provider-neutral opaque calendar mutation references."""

from __future__ import annotations

import pytest

from integrations.calendar_refs import (
    InvalidCalendarRef,
    decode_event_ref,
    decode_series_ref,
    encode_event_ref,
    encode_series_ref,
)


def test_event_ref_round_trips_all_caldav_routing_fields() -> None:
    """CalDAV occurrence identity and href survive opaque encoding."""
    value = encode_event_ref(
        provider="caldav",
        calendar_ref="https://caldav.example/home/",
        event_id="uid-123",
        recurrence_id="2026-07-22T09:00:00-05:00",
        href="https://caldav.example/home/uid-123.ics",
    )

    target = decode_event_ref(value, provider="caldav")

    assert value.startswith("calref1_")
    assert target.calendar_ref == "https://caldav.example/home/"
    assert target.event_id == "uid-123"
    assert target.recurrence_id == "2026-07-22T09:00:00-05:00"
    assert target.href == "https://caldav.example/home/uid-123.ics"


def test_series_ref_round_trips_google_series_id() -> None:
    """Google's native recurring event ID is retained inside series_ref."""
    value = encode_series_ref(
        provider="google",
        calendar_ref="primary",
        event_id="recurring-event-123",
    )

    target = decode_series_ref(value, provider="google")

    assert target.calendar_ref == "primary"
    assert target.event_id == "recurring-event-123"
    assert target.recurrence_id is None


@pytest.mark.parametrize("value", ["", "event-123", "calref1_not-base64"])
def test_invalid_refs_are_rejected(value: str) -> None:
    """Malformed or non-reference strings fail closed."""
    with pytest.raises(InvalidCalendarRef, match="invalid event_ref"):
        decode_event_ref(value, provider="google")


def test_ref_kind_and_provider_cannot_be_mixed() -> None:
    """A reference cannot cross its operation kind or provider boundary."""
    value = encode_event_ref(
        provider="google", calendar_ref="primary", event_id="event-123",
    )

    with pytest.raises(InvalidCalendarRef, match="invalid series_ref"):
        decode_series_ref(value, provider="google")
    with pytest.raises(InvalidCalendarRef, match="different calendar provider"):
        decode_event_ref(value, provider="caldav")
