"""Agent tool: update every occurrence in a recurring calendar series."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from config import load_config
from integrations import broker_client

logger = logging.getLogger(__name__)


async def update_event_series(
    integration_id: str,
    series_ref: str,
    summary: str | None = None,
    start: str | None = None,
    end: str | None = None,
    description: str | None = None,
    location: str | None = None,
    attendees: list[str] | None = None,
    recurrence_rule: str | None = None,
    time_zone: str | None = None,
) -> str:
    """Update supplied fields across an entire recurring series."""
    args: dict[str, Any] = {"series_ref": series_ref}
    changes = {
        "summary": summary,
        "start": start,
        "end": end,
        "description": description,
        "location": location,
        "attendees": attendees,
        "recurrence_rule": recurrence_rule,
        "time_zone": time_zone,
    }
    args.update({key: value for key, value in changes.items() if value is not None})
    if len(args) == 1:
        return (
            "No fields to update — provide at least one of summary, start, end, "
            "description, location, attendees, recurrence_rule, or time_zone."
        )

    app_sock = load_config().integrations.app_sock_path
    try:
        result = await broker_client.call(
            integration_id, "update_event_series", args, app_sock_path=app_sock,
        )
    except broker_client.IntegrationNotConnected:
        return f"Integration {integration_id!r} is not connected."
    except broker_client.IntegrationWriteDenied:
        return f"Writes are disabled for {integration_id!r}."
    except broker_client.IntegrationError as exc:
        logger.warning("update_event_series(%r) failed: %s", integration_id, exc)
        return f"Failed to update event series via {integration_id!r}: {exc}"

    event = result.get("event", {})
    title = event.get("summary") or "(no title)"
    returned_ref = result.get("series_ref") or event.get("series_ref") or series_ref
    return f"Updated recurring series '{title}' [series_ref: {returned_ref}]."


def build_update_event_series_tool(integration_ids: Iterable[str]) -> Callable[..., Any]:
    """Turn-scoped wrapper whose docstring advertises the current IDs."""
    ids = sorted(integration_ids)
    ids_line = ", ".join(repr(i) for i in ids) if ids else "(none registered)"

    async def _update_event_series(
        integration_id: str,
        series_ref: str,
        summary: str | None = None,
        start: str | None = None,
        end: str | None = None,
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
        recurrence_rule: str | None = None,
        time_zone: str | None = None,
    ) -> str:
        return await update_event_series(
            integration_id, series_ref, summary, start, end,
            description, location, attendees, recurrence_rule, time_zone,
        )

    _update_event_series.__name__ = update_event_series.__name__
    _update_event_series.__doc__ = (
        "Update every occurrence in a recurring calendar series. Use the "
        "series_ref returned by list_events; use update_event when only one "
        f"occurrence should change. Valid integration IDs: {ids_line}.\n\n"
        "Args:\n"
        "    integration_id: Which integration the series belongs to.\n"
        "    series_ref: Opaque whole-series reference from list_events.\n"
        "    summary: New title (omit to keep current).\n"
        "    start: New series start time, RFC 3339 or date.\n"
        "    end: New series end time, RFC 3339 or date.\n"
        "    description: New description; empty clears it.\n"
        "    location: New location; empty clears it.\n"
        "    attendees: New attendee email list (replaces existing and notifies guests).\n"
        "    recurrence_rule: New RFC 5545 recurrence rule, such as FREQ=WEEKLY;COUNT=8.\n"
        "    time_zone: IANA zone when changing a timed recurrence schedule.\n"
    )
    return _update_event_series
