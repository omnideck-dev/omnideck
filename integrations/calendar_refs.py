"""Opaque references shared by calendar integration brokers.

The agent should not have to understand provider event IDs, CalDAV hrefs, or
RECURRENCE-ID values.  Brokers encode those routing details into an opaque
reference and decode it only after the integration permission gate has run.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any, Literal

Provider = Literal["caldav", "google"]


class InvalidCalendarRef(ValueError):
    """Raised when an event or series reference is malformed or mismatched."""


@dataclass(frozen=True)
class CalendarTarget:
    """Provider routing data recovered from an opaque calendar reference."""

    provider: Provider
    calendar_ref: str
    event_id: str
    recurrence_id: str | None = None
    href: str | None = None


def encode_event_ref(
    *,
    provider: Provider,
    calendar_ref: str,
    event_id: str,
    recurrence_id: str | None = None,
    href: str | None = None,
) -> str:
    """Encode an exact event occurrence target."""
    return _encode("event", provider, calendar_ref, event_id, recurrence_id, href)


def encode_series_ref(
    *,
    provider: Provider,
    calendar_ref: str,
    event_id: str,
    href: str | None = None,
) -> str:
    """Encode a whole recurring-series target."""
    return _encode("series", provider, calendar_ref, event_id, None, href)


def decode_event_ref(value: str, *, provider: Provider) -> CalendarTarget:
    """Decode and validate an exact-occurrence reference for ``provider``."""
    return _decode(value, kind="event", provider=provider)


def decode_series_ref(value: str, *, provider: Provider) -> CalendarTarget:
    """Decode and validate a whole-series reference for ``provider``."""
    return _decode(value, kind="series", provider=provider)


def _encode(
    kind: Literal["event", "series"],
    provider: Provider,
    calendar_ref: str,
    event_id: str,
    recurrence_id: str | None,
    href: str | None,
) -> str:
    payload: dict[str, Any] = {
        "v": 1,
        "k": kind,
        "p": provider,
        "c": calendar_ref,
        "i": event_id,
    }
    if recurrence_id is not None:
        payload["r"] = recurrence_id
    if href is not None:
        payload["h"] = href
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8"),
    ).decode("ascii").rstrip("=")
    return f"calref1_{encoded}"


def _decode(value: str, *, kind: str, provider: Provider) -> CalendarTarget:
    if not isinstance(value, str) or not value.startswith("calref1_"):
        raise InvalidCalendarRef(f"invalid {kind}_ref")
    encoded = value.removeprefix("calref1_")
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        payload = json.loads(raw)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidCalendarRef(f"invalid {kind}_ref") from exc
    if not isinstance(payload, dict):
        raise InvalidCalendarRef(f"invalid {kind}_ref")
    if payload.get("v") != 1 or payload.get("k") != kind:
        raise InvalidCalendarRef(f"invalid {kind}_ref")
    if payload.get("p") != provider:
        raise InvalidCalendarRef(f"{kind}_ref belongs to a different calendar provider")
    calendar_ref = payload.get("c")
    event_id = payload.get("i")
    recurrence_id = payload.get("r")
    href = payload.get("h")
    if not isinstance(calendar_ref, str) or not calendar_ref:
        raise InvalidCalendarRef(f"invalid {kind}_ref")
    if not isinstance(event_id, str) or not event_id:
        raise InvalidCalendarRef(f"invalid {kind}_ref")
    if recurrence_id is not None and (not isinstance(recurrence_id, str) or not recurrence_id):
        raise InvalidCalendarRef(f"invalid {kind}_ref")
    if href is not None and (not isinstance(href, str) or not href):
        raise InvalidCalendarRef(f"invalid {kind}_ref")
    return CalendarTarget(
        provider=provider,
        calendar_ref=calendar_ref,
        event_id=event_id,
        recurrence_id=recurrence_id,
        href=href,
    )
