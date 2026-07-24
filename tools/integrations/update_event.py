"""Agent tool: update an existing event on a connected calendar."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from config import load_config
from integrations import broker_client

logger = logging.getLogger(__name__)


async def update_event(
    integration_id: str,
    event_ref: str,
    summary: str | None = None,
    start: str | None = None,
    end: str | None = None,
    description: str | None = None,
    location: str | None = None,
    attendees: list[str] | None = None,
) -> str:
    """Update fields on an existing calendar event.

    Only the fields you provide are changed; omitted fields stay as-is.

    Args:
        integration_id: Identifier of the calendar integration.
        event_ref: Opaque exact-occurrence reference from ``list_events``.
        summary: New event title (omit to keep current).
        start: New start time — RFC 3339 datetime or date string.
        end: New end time — same format as start.
        description: New description (empty clears it; omit to keep current).
        location: New location (empty clears it; omit to keep current).
        attendees: New attendee list — replaces the existing list entirely.

    Returns:
        A confirmation with the updated event, or an error notice.
    """
    app_sock = load_config().integrations.app_sock_path
    args: dict[str, Any] = {
        "event_ref": event_ref,
    }
    if summary is not None:
        args["summary"] = summary
    if start is not None:
        args["start"] = start
    if end is not None:
        args["end"] = end
    if description is not None:
        args["description"] = description
    if location is not None:
        args["location"] = location
    if attendees is not None:
        args["attendees"] = attendees

    if len(args) == 1:
        return "No fields to update — provide at least one of summary, start, end, description, location, or attendees."

    try:
        result = await broker_client.call(
            integration_id, "update_event", args, app_sock_path=app_sock,
        )
    except broker_client.IntegrationNotConnected:
        return f"Integration {integration_id!r} is not connected."
    except broker_client.IntegrationWriteDenied:
        return f"Writes are disabled for {integration_id!r}."
    except broker_client.IntegrationError as exc:
        logger.warning(
            "update_event(%r, %r) failed: %s", integration_id, event_ref, exc,
        )
        return f"Failed to update event via {integration_id!r}: {exc}"

    event = result.get("event", {})
    title = event.get("summary") or "(no title)"
    returned_ref = event.get("event_ref") or event_ref
    return f"Updated event '{title}' [event_ref: {returned_ref}]."


def build_update_event_tool(integration_ids: Iterable[str]) -> Callable[..., Any]:
    """Turn-scoped wrapper whose docstring advertises the current IDs."""
    ids = sorted(integration_ids)
    ids_line = ", ".join(repr(i) for i in ids) if ids else "(none registered)"

    async def _update_event(
        integration_id: str,
        event_ref: str,
        summary: str | None = None,
        start: str | None = None,
        end: str | None = None,
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
    ) -> str:
        return await update_event(
            integration_id, event_ref,
            summary, start, end, description, location, attendees,
        )

    _update_event.__name__ = update_event.__name__
    _update_event.__doc__ = (
        "Update an existing event on a connected calendar. Only supplied fields "
        "are changed. event_ref always targets exactly the listed occurrence; "
        "use update_event_series for every occurrence. "
        f"Valid integration IDs: {ids_line}.\n\n"
        "Args:\n"
        "    integration_id: Which integration the calendar belongs to.\n"
        "    event_ref: Opaque exact-occurrence reference from list_events.\n"
        "    summary: New title (omit = keep current).\n"
        "    start: New start time, RFC 3339 or date.\n"
        "    end: New end time, RFC 3339 or date.\n"
        "    description: New description.\n"
        "    location: New location.\n"
        "    attendees: New attendee email list (replaces existing).\n\n"
        "Returns:\n"
        "    Plain text — a confirmation, or an error notice.\n"
    )
    return _update_event
