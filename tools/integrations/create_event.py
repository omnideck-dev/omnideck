"""Agent tool: create an event on a connected calendar."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from config import load_config
from integrations import broker_client

logger = logging.getLogger(__name__)


async def create_event(
    integration_id: str,
    calendar_ref: str,
    summary: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
    attendees: list[str] | None = None,
) -> str:
    """Create a new event on a calendar.

    Args:
        integration_id: Identifier of the calendar integration.
        calendar_ref: Opaque calendar reference from ``list_calendars``.
        summary: Event title.
        start: Start time — RFC 3339 datetime (e.g. ``2026-05-10T09:00:00-05:00``)
            or a date string (``2026-05-10``) for all-day events.
        end: End time — same format as start.
        description: Optional event description or notes.
        location: Optional location string.
        attendees: Optional list of attendee email addresses.

    Returns:
        A confirmation with the opaque event_ref and summary, or an error notice.
    """
    app_sock = load_config().integrations.app_sock_path
    args: dict[str, Any] = {
        "calendar_ref": calendar_ref,
        "summary": summary,
        "start": start,
        "end": end,
    }
    if description:
        args["description"] = description
    if location:
        args["location"] = location
    if attendees:
        args["attendees"] = attendees
    try:
        result = await broker_client.call(
            integration_id, "create_event", args, app_sock_path=app_sock,
        )
    except broker_client.IntegrationNotConnected:
        return f"Integration {integration_id!r} is not connected."
    except broker_client.IntegrationWriteDenied:
        return f"Writes are disabled for {integration_id!r}."
    except broker_client.IntegrationError as exc:
        logger.warning(
            "create_event(%r, %r) failed: %s", integration_id, calendar_ref, exc,
        )
        return f"Failed to create event via {integration_id!r}: {exc}"

    event = result.get("event", {})
    event_ref = event.get("event_ref", "")
    title = event.get("summary", summary)
    start_str = event.get("start", start)
    return f"Created event '{title}' at {start_str} [event_ref: {event_ref}]."


def build_create_event_tool(integration_ids: Iterable[str]) -> Callable[..., Any]:
    """Turn-scoped wrapper whose docstring advertises the current IDs."""
    ids = sorted(integration_ids)
    ids_line = ", ".join(repr(i) for i in ids) if ids else "(none registered)"

    async def _create_event(
        integration_id: str,
        calendar_ref: str,
        summary: str,
        start: str,
        end: str,
        description: str = "",
        location: str = "",
        attendees: list[str] | None = None,
    ) -> str:
        return await create_event(
            integration_id, calendar_ref, summary, start, end,
            description, location, attendees,
        )

    _create_event.__name__ = create_event.__name__
    _create_event.__doc__ = (
        "Create a new event on a connected calendar. Use list_calendars first to "
        "get calendar_ref. "
        f"Valid integration IDs: {ids_line}.\n\n"
        "Args:\n"
        "    integration_id: Which integration the calendar belongs to.\n"
        "    calendar_ref: Opaque calendar reference from list_calendars.\n"
        "    summary: Event title.\n"
        "    start: RFC 3339 datetime (2026-05-10T09:00:00-05:00) or date (2026-05-10) for all-day.\n"
        "    end: End time, same format as start.\n"
        "    description: Optional event description.\n"
        "    location: Optional location string.\n"
        "    attendees: Optional list of attendee email addresses.\n\n"
        "Returns:\n"
        "    Plain text — a confirmation with event_ref, or an error notice.\n"
    )
    return _create_event
