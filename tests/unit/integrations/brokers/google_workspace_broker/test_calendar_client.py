"""Focused tests for Google Calendar write request construction."""

from __future__ import annotations

from typing import Any

import pytest

from integrations.brokers.google_workspace_broker._calendar_client import CalendarClient


class _Request:
    def __init__(self, result: Any = None) -> None:
        self.result = result

    def execute(self) -> Any:
        return self.result


class _Events:
    def __init__(self) -> None:
        self.list_calls: list[dict[str, Any]] = []
        self.insert_calls: list[dict[str, Any]] = []
        self.patch_calls: list[dict[str, Any]] = []
        self.delete_calls: list[dict[str, Any]] = []

    def list(self, **kwargs: Any) -> _Request:
        self.list_calls.append(kwargs)
        return _Request({
            "summary": "Work",
            "items": [{
                "id": "dentist-1",
                "summary": "Dentist appointment",
            }],
        })

    def insert(self, **kwargs: Any) -> _Request:
        self.insert_calls.append(kwargs)
        return _Request({"id": "event-1", **kwargs["body"]})

    def patch(self, **kwargs: Any) -> _Request:
        self.patch_calls.append(kwargs)
        return _Request({"id": kwargs["eventId"], **kwargs["body"]})

    def delete(self, **kwargs: Any) -> _Request:
        self.delete_calls.append(kwargs)
        return _Request()


class _Service:
    def __init__(self) -> None:
        self.event_api = _Events()

    def events(self) -> _Events:
        return self.event_api


def _client(monkeypatch: pytest.MonkeyPatch) -> tuple[CalendarClient, _Events]:
    client = CalendarClient.__new__(CalendarClient)
    service = _Service()
    monkeypatch.setattr(client, "_service", lambda: service)
    return client, service.event_api


def test_create_recurring_event_sends_invites_and_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Google receives a native recurrence, IANA zone, and invite delivery flag."""
    client, events = _client(monkeypatch)

    result = client.create_event(
        "primary",
        "Weekly sync",
        "2026-07-16T09:00:00-05:00",
        "2026-07-16T09:30:00-05:00",
        attendees=["guest@example.com"],
        recurrence_rule="FREQ=WEEKLY;COUNT=4",
        time_zone="America/Chicago",
    )

    call = events.insert_calls[0]
    assert call["sendUpdates"] == "all"
    assert call["body"]["recurrence"] == ["RRULE:FREQ=WEEKLY;COUNT=4"]
    assert call["body"]["start"]["timeZone"] == "America/Chicago"
    assert call["body"]["attendees"] == [{"email": "guest@example.com"}]
    assert result["id"] == "event-1"


def test_search_events_uses_native_free_text_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Google's native q filter is combined with occurrence expansion and dates."""
    client, events = _client(monkeypatch)

    result, calendar_name = client.search_events(
        "primary",
        "  dentist  ",
        days_forward=730,
        days_back=30,
        limit=20,
    )

    call = events.list_calls[0]
    assert call["calendarId"] == "primary"
    assert call["q"] == "dentist"
    assert call["singleEvents"] is True
    assert call["orderBy"] == "startTime"
    assert call["maxResults"] == 20
    assert result[0]["id"] == "dentist-1"
    assert calendar_name == "Work"


def test_search_events_rejects_empty_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty Google query is rejected before an API request is made."""
    client, events = _client(monkeypatch)

    with pytest.raises(ValueError, match="query must not be empty"):
        client.search_events("primary", "   ")

    assert events.list_calls == []


def test_create_timed_recurrence_requires_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Google recurrence cannot be created with an ambiguous fixed-offset zone."""
    client, events = _client(monkeypatch)

    with pytest.raises(ValueError, match="time_zone is required"):
        client.create_event(
            "primary",
            "Weekly sync",
            "2026-07-16T09:00:00-05:00",
            "2026-07-16T09:30:00-05:00",
            recurrence_rule="FREQ=WEEKLY;COUNT=4",
        )

    assert events.insert_calls == []


def test_series_update_and_delete_notify_guests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Series changes and cancellations request Google guest notifications."""
    client, events = _client(monkeypatch)

    client.update_event(
        "primary",
        "series-1",
        recurrence_rule="FREQ=WEEKLY;COUNT=8",
        time_zone="America/Chicago",
    )
    client.delete_event("primary", "series-1")

    assert events.patch_calls[0]["sendUpdates"] == "all"
    assert events.patch_calls[0]["body"]["recurrence"] == [
        "RRULE:FREQ=WEEKLY;COUNT=8",
    ]
    assert events.delete_calls[0]["sendUpdates"] == "all"
