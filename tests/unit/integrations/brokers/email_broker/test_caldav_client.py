"""Focused tests for CalDAV calendar writes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from caldav.lib import error as caldav_error
from icalendar import Calendar as ICalendar
from icalendar import Event as ICalendarEvent

from integrations.brokers.email_broker._caldav_client import CalDavClient


class _StubResource:
    def __init__(self, calendar: ICalendar) -> None:
        self.icalendar_instance = calendar
        self.save_calls = 0
        self.delete_calls = 0

    def save(self) -> None:
        self.save_calls += 1

    def delete(self) -> None:
        self.delete_calls += 1


def _event_resource(
    *,
    uid: str = "icloud-event-123",
    summary: str = "Project review",
    start: str = "2026-07-15T09:00:00-05:00",
    end: str = "2026-07-15T10:00:00-05:00",
) -> _StubResource:
    calendar = ICalendar()
    component = ICalendarEvent()
    component.add("uid", uid)
    component.add("summary", summary)
    component.add("dtstart", datetime.fromisoformat(start))
    component.add("dtend", datetime.fromisoformat(end))
    calendar.add_component(component)
    return _StubResource(calendar)


class _StubCalendar:
    def __init__(self) -> None:
        self.added: list[dict[str, Any]] = []
        self.resources: dict[str, _StubResource] = {}

    def add_event(self, **properties: Any) -> Any:
        self.added.append(properties)
        resource = _event_resource()
        component = next(iter(resource.icalendar_instance.walk("VEVENT")))
        component.clear()
        component.add("uid", "icloud-event-123")
        for key, value in properties.items():
            component.add(key, value)
        self.resources["icloud-event-123"] = resource
        return resource

    def get_event_by_uid(self, uid: str) -> _StubResource:
        try:
            return self.resources[uid]
        except KeyError as exc:
            raise caldav_error.NotFoundError(uid) from exc


class _StubDavClient:
    def __init__(self, calendar: _StubCalendar) -> None:
        self.stub_calendar = calendar
        self.urls: list[str] = []

    def calendar(self, *, url: str) -> _StubCalendar:
        self.urls.append(url)
        return self.stub_calendar


def _connected_client(calendar: _StubCalendar) -> CalDavClient:
    client = CalDavClient(url="https://caldav.example", username="u", password="p")
    client._client = _StubDavClient(calendar)  # type: ignore[assignment]
    client._principal = object()
    return client


@pytest.mark.asyncio
async def test_create_event_adds_vevent_and_returns_wire_event() -> None:
    calendar = _StubCalendar()
    client = _connected_client(calendar)

    event = await client.create_event(
        "https://caldav.icloud.com/123/calendars/home/",
        "Project review",
        "2026-07-15T09:00:00-05:00",
        "2026-07-15T10:00:00-05:00",
        "Review the release",
        "Room 4",
        ["alice@example.com", "mailto:bob@example.com"],
    )

    assert event.model_dump() == {
        "uid": "icloud-event-123",
        "summary": "Project review",
        "start": "2026-07-15T09:00:00-05:00",
        "end": "2026-07-15T10:00:00-05:00",
        "location": "Room 4",
        "description": "Review the release",
    }
    assert calendar.added == [{
        "summary": "Project review",
        "dtstart": datetime.fromisoformat("2026-07-15T09:00:00-05:00"),
        "dtend": datetime.fromisoformat("2026-07-15T10:00:00-05:00"),
        "description": "Review the release",
        "location": "Room 4",
        "attendee": ["mailto:alice@example.com", "mailto:bob@example.com"],
    }]


@pytest.mark.asyncio
async def test_create_event_rejects_invalid_time_range_before_network_call() -> None:
    calendar = _StubCalendar()
    client = _connected_client(calendar)

    with pytest.raises(ValueError, match="end must be after start"):
        await client.create_event(
            "https://caldav.example/home/",
            "Backwards",
            "2026-07-15T10:00:00-05:00",
            "2026-07-15T09:00:00-05:00",
        )

    assert calendar.added == []


@pytest.mark.asyncio
async def test_create_event_rejects_datetime_without_offset() -> None:
    client = _connected_client(_StubCalendar())

    with pytest.raises(ValueError, match="start datetime must include a UTC offset"):
        await client.create_event(
            "https://caldav.example/home/",
            "Floating",
            "2026-07-15T09:00:00",
            "2026-07-15T10:00:00",
        )


@pytest.mark.asyncio
async def test_update_event_changes_only_supplied_fields_and_saves() -> None:
    calendar = _StubCalendar()
    resource = _event_resource()
    calendar.resources["icloud-event-123"] = resource
    client = _connected_client(calendar)

    event = await client.update_event(
        "https://caldav.example/home/",
        "icloud-event-123",
        summary="Updated review",
        location="Room 9",
        attendees=["alice@example.com"],
    )

    assert event.summary == "Updated review"
    assert event.location == "Room 9"
    assert event.start == "2026-07-15T09:00:00-05:00"
    assert resource.save_calls == 1
    component = next(iter(resource.icalendar_instance.walk("VEVENT")))
    assert str(component.get("attendee")) == "mailto:alice@example.com"


@pytest.mark.asyncio
async def test_delete_event_resolves_uid_and_deletes_resource() -> None:
    calendar = _StubCalendar()
    resource = _event_resource()
    calendar.resources["icloud-event-123"] = resource
    client = _connected_client(calendar)

    await client.delete_event(
        "https://caldav.example/home/", "icloud-event-123",
    )

    assert resource.delete_calls == 1


@pytest.mark.asyncio
async def test_update_event_translates_missing_uid_to_lookup_error() -> None:
    client = _connected_client(_StubCalendar())

    with pytest.raises(LookupError, match="event not found: missing"):
        await client.update_event(
            "https://caldav.example/home/", "missing", summary="Nope",
        )
