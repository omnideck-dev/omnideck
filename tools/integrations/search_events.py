"""Agent tool: search one calendar for matching events."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from config import load_config
from integrations import broker_client
from tools.integrations.list_events import _format_event

logger = logging.getLogger(__name__)


async def search_events(
    integration_id: str,
    calendar_ref: str,
    query: str,
    days_forward: int = 365,
    days_back: int = 0,
    limit: int = 50,
) -> str:
    """Search one calendar for events matching free text.

    Recurring events are returned as exact occurrences, with the same
    ``event_ref`` and ``series_ref`` affordances as :func:`list_events`.

    Args:
        integration_id: Identifier of the calendar integration.
        calendar_ref: Opaque calendar reference from ``list_calendars``.
        query: Text to match in event metadata.
        days_forward: How many future days to search (default 365).
        days_back: How many past days to search (default 0).
        limit: Maximum matches to return (1-200, default 50).

    Returns:
        A plain-text bulleted list of matching events, or a short empty/error notice.
    """
    app_sock = load_config().integrations.app_sock_path
    try:
        result = await broker_client.call(
            integration_id,
            "search_events",
            {
                "calendar_ref": calendar_ref,
                "query": query,
                "days_forward": days_forward,
                "days_back": days_back,
                "limit": limit,
            },
            app_sock_path=app_sock,
        )
    except broker_client.IntegrationNotConnected:
        return f"Integration {integration_id!r} is not connected."
    except broker_client.IntegrationError as exc:
        logger.warning(
            "search_events(%r, %r, %r) failed: %s",
            integration_id,
            calendar_ref,
            query,
            exc,
        )
        return f"Failed to search events for {integration_id!r}: {exc}"

    events = result.get("events", [])
    label = result.get("calendar_name") or calendar_ref
    if not events:
        return f"No events matching {query!r} on {label!r} in this range."
    lines = [_format_event(event) for event in events]
    return f"Matches for {query!r} on {label!r} ({len(lines)}):\n" + "\n".join(lines)


def build_search_events_tool(integration_ids: Iterable[str]) -> Callable[..., Any]:
    """Turn-scoped wrapper whose docstring advertises the current IDs."""
    ids = sorted(integration_ids)
    ids_line = ", ".join(repr(integration_id) for integration_id in ids)
    if not ids_line:
        ids_line = "(none registered)"

    async def _search_events(
        integration_id: str,
        calendar_ref: str,
        query: str,
        days_forward: int = 365,
        days_back: int = 0,
        limit: int = 50,
    ) -> str:
        return await search_events(
            integration_id,
            calendar_ref,
            query,
            days_forward,
            days_back,
            limit,
        )

    _search_events.__name__ = search_events.__name__
    _search_events.__doc__ = (
        "Search one calendar for events matching free text. Results are "
        "exact occurrences: event_ref targets that occurrence and series_ref "
        "targets its recurring series. Search covers title, description, and "
        "location; a provider may also match participant metadata. "
        f"Valid integration IDs: {ids_line}.\n\n"
        "Args:\n"
        "    integration_id: Which integration the calendar belongs to.\n"
        "    calendar_ref: Opaque calendar reference from list_calendars.\n"
        "    query: Free text to search for.\n"
        "    days_forward: Future days to search (default 365).\n"
        "    days_back: Past days to search (default 0).\n"
        "    limit: Maximum matches to return (1-200, default 50).\n\n"
        "Returns:\n"
        "    Plain text in the same per-event format as list_events, or a "
        "short empty/error notice.\n"
    )
    return _search_events
