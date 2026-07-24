"""Agent tool: delete an event from a connected calendar."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from config import load_config
from integrations import broker_client

logger = logging.getLogger(__name__)


async def delete_event(
    integration_id: str,
    event_ref: str,
) -> str:
    """Delete an event from a calendar.

    Args:
        integration_id: Identifier of the calendar integration.
        event_ref: Opaque exact-occurrence reference from ``list_events``.

    Returns:
        A confirmation, or an error notice.
    """
    app_sock = load_config().integrations.app_sock_path
    try:
        await broker_client.call(
            integration_id,
            "delete_event",
            {"event_ref": event_ref},
            app_sock_path=app_sock,
        )
    except broker_client.IntegrationNotConnected:
        return f"Integration {integration_id!r} is not connected."
    except broker_client.IntegrationWriteDenied:
        return f"Writes are disabled for {integration_id!r}."
    except broker_client.IntegrationError as exc:
        logger.warning(
            "delete_event(%r, %r) failed: %s", integration_id, event_ref, exc,
        )
        return f"Failed to delete event via {integration_id!r}: {exc}"

    return f"Deleted event occurrence [event_ref: {event_ref}]."


def build_delete_event_tool(integration_ids: Iterable[str]) -> Callable[..., Any]:
    """Turn-scoped wrapper whose docstring advertises the current IDs."""
    ids = sorted(integration_ids)
    ids_line = ", ".join(repr(i) for i in ids) if ids else "(none registered)"

    async def _delete_event(
        integration_id: str,
        event_ref: str,
    ) -> str:
        return await delete_event(integration_id, event_ref)

    _delete_event.__name__ = delete_event.__name__
    _delete_event.__doc__ = (
        "Delete exactly one listed event occurrence from a connected calendar. "
        "For a recurring event this leaves the rest of the series intact; use "
        "delete_event_series to delete every occurrence. "
        f"Valid integration IDs: {ids_line}.\n\n"
        "Args:\n"
        "    integration_id: Which integration the calendar belongs to.\n"
        "    event_ref: Opaque exact-occurrence reference from list_events.\n\n"
        "Returns:\n"
        "    Plain text — a confirmation, or an error notice.\n"
    )
    return _delete_event
