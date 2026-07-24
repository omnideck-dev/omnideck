"""Google Calendar operations via the Calendar API v3."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from integrations.calendar_recurrence import normalize_recurrence_rule, normalize_time_zone

logger = logging.getLogger(__name__)


class CalendarClient:
    """Thin wrapper around the Calendar v3 API."""

    def __init__(self, creds: Credentials) -> None:
        self._creds = creds

    def _service(self):
        return build("calendar", "v3", credentials=self._creds, cache_discovery=False)

    def list_calendars(self) -> list[dict[str, Any]]:
        """List all calendar entries visible to the user."""
        results: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            resp = (
                self._service().calendarList()
                .list(pageToken=page_token)
                .execute()
            )
            results.extend(resp.get("items", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return results

    def list_events(
        self,
        calendar_id: str = "primary",
        *,
        days_forward: int = 30,
        days_back: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """List events in a date range, recurring events expanded.

        Returns (events, calendar_name) where calendar_name is the
        display name from the first page of results.
        """
        return self._list_events(
            calendar_id,
            days_forward=days_forward,
            days_back=days_back,
            limit=limit,
        )

    def search_events(
        self,
        calendar_id: str,
        query: str,
        *,
        days_forward: int = 365,
        days_back: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Search a date range using Google Calendar's free-text query."""
        query = query.strip()
        if not query:
            raise ValueError("query must not be empty")
        return self._list_events(
            calendar_id,
            days_forward=days_forward,
            days_back=days_back,
            limit=limit,
            query=query,
        )

    def _list_events(
        self,
        calendar_id: str,
        *,
        days_forward: int,
        days_back: int,
        limit: int,
        query: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Run one paginated, occurrence-expanded Calendar events query."""
        now = datetime.now(UTC)
        time_min = (now - timedelta(days=days_back)).isoformat()
        time_max = (now + timedelta(days=days_forward)).isoformat()

        results: list[dict[str, Any]] = []
        cal_name: str | None = None
        page_token: str | None = None
        while len(results) < limit:
            page_size = min(limit - len(results), 250)
            request = {
                "calendarId": calendar_id,
                "timeMin": time_min,
                "timeMax": time_max,
                "maxResults": page_size,
                "pageToken": page_token,
                "singleEvents": True,
                "orderBy": "startTime",
            }
            if query is not None:
                request["q"] = query
            resp = self._service().events().list(**request).execute()
            if cal_name is None:
                cal_name = resp.get("summary")
            results.extend(resp.get("items", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return results[:limit], cal_name

    def create_event(
        self,
        calendar_id: str,
        summary: str,
        start: str,
        end: str,
        *,
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
        recurrence_rule: str | None = None,
        time_zone: str | None = None,
    ) -> dict[str, Any]:
        """Create an event. start/end are RFC 3339 timestamps or date strings."""
        recurrence = normalize_recurrence_rule(recurrence_rule)
        zone = normalize_time_zone(time_zone)
        if recurrence and "T" in start and zone is None:
            raise ValueError("time_zone is required for a recurring timed event")
        body: dict[str, Any] = {"summary": summary}
        body["start"] = _time_body(start, zone)
        body["end"] = _time_body(end, zone)
        if description:
            body["description"] = description
        if location:
            body["location"] = location
        if attendees:
            body["attendees"] = [{"email": a} for a in attendees]
        if recurrence:
            body["recurrence"] = [f"RRULE:{recurrence}"]
        request: dict[str, Any] = {"calendarId": calendar_id, "body": body}
        if attendees:
            request["sendUpdates"] = "all"
        return self._service().events().insert(**request).execute()

    def update_event(
        self,
        calendar_id: str,
        event_id: str,
        *,
        summary: str | None = None,
        start: str | None = None,
        end: str | None = None,
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
        recurrence_rule: str | None = None,
        time_zone: str | None = None,
    ) -> dict[str, Any]:
        """Patch an existing event. Only supplied fields are updated."""
        body: dict[str, Any] = {}
        if summary is not None:
            body["summary"] = summary
        if start is not None:
            body["start"] = _time_body(start, normalize_time_zone(time_zone))
        if end is not None:
            body["end"] = _time_body(end, normalize_time_zone(time_zone))
        if description is not None:
            body["description"] = description
        if location is not None:
            body["location"] = location
        if attendees is not None:
            body["attendees"] = [{"email": a} for a in attendees]
        recurrence = normalize_recurrence_rule(recurrence_rule)
        if recurrence is not None:
            zone = normalize_time_zone(time_zone)
            if start is not None and "T" in start and zone is None:
                raise ValueError("time_zone is required when changing a timed recurrence")
            body["recurrence"] = [f"RRULE:{recurrence}"]
        return (
            self._service().events()
            .patch(
                calendarId=calendar_id,
                eventId=event_id,
                body=body,
                sendUpdates="all",
            )
            .execute()
        )

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        """Delete an event from a calendar."""
        self._service().events().delete(
            calendarId=calendar_id, eventId=event_id, sendUpdates="all",
        ).execute()


def _time_body(value: str, time_zone: str | None = None) -> dict[str, str]:
    """Build a Calendar API start/end block from a date or datetime string.

    Pure date strings (YYYY-MM-DD) use the ``date`` key; anything longer
    is treated as an RFC 3339 ``dateTime``.
    """
    if len(value) == 10 and value[4] == "-" and value[7] == "-":
        return {"date": value}
    result = {"dateTime": value}
    if time_zone:
        result["timeZone"] = time_zone
    return result
