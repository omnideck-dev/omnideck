"""Provider-neutral validation for RFC 5545 recurrence rules."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from icalendar import vRecur


def normalize_recurrence_rule(value: str | None) -> str | None:
    """Return a canonical RRULE value, or ``None`` for a one-time event.

    Agent tools accept the rule value with or without an ``RRULE:`` prefix.
    Newlines are rejected so one argument can never inject extra iCalendar
    properties.
    """
    if value is None or not value.strip():
        return None
    rule = value.strip()
    if "\r" in rule or "\n" in rule:
        raise ValueError("recurrence_rule must contain exactly one RRULE")
    if rule.upper().startswith("RRULE:"):
        rule = rule[6:].strip()
    try:
        parsed = vRecur.from_ical(rule)
    except (TypeError, ValueError) as exc:
        raise ValueError("recurrence_rule must be a valid RFC 5545 RRULE") from exc
    if "FREQ" not in parsed:
        raise ValueError("recurrence_rule must include FREQ")
    return parsed.to_ical().decode("ascii")


def normalize_time_zone(value: str | None) -> str | None:
    """Validate and normalize an optional IANA time-zone name."""
    if value is None or not value.strip():
        return None
    name = value.strip()
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("time_zone must be a valid IANA time-zone name") from exc
    return name
