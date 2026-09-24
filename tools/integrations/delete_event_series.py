"""Agent tool: delete an entire recurring calendar series."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from config import load_config
from integrations import broker_client

logger = logging.getLogger(__name__)


async def delete_event_series(integration_id: str, series_ref: str) -> str:
    """Permanently delete every occurrence in a recurring series."""
    app_sock = load_config().integrations.app_sock_path
    try:
        await broker_client.call(
            integration_id,
            "delete_event_series",
            {"series_ref": series_ref},
            app_sock_path=app_sock,
        )
    except broker_client.IntegrationNotConnected:
        return f"Integration {integration_id!r} is not connected."
    except broker_client.IntegrationWriteDenied:
        return f"Writes are disabled for {integration_id!r}."
    except broker_client.IntegrationError as exc:
        logger.warning("delete_event_series(%r) failed: %s", integration_id, exc)
        return f"Failed to delete event series via {integration_id!r}: {exc}"
    return f"Deleted recurring series [series_ref: {series_ref}]."


def build_delete_event_series_tool(integration_ids: Iterable[str]) -> Callable[..., Any]:
    """Turn-scoped wrapper whose docstring advertises the current IDs."""
    ids = sorted(integration_ids)
    ids_line = ", ".join(repr(i) for i in ids) if ids else "(none registered)"

    async def _delete_event_series(integration_id: str, series_ref: str) -> str:
        return await delete_event_series(integration_id, series_ref)

    _delete_event_series.__name__ = delete_event_series.__name__
    _delete_event_series.__doc__ = (
        "Permanently delete every occurrence in a recurring calendar series. "
        "Use delete_event when only one occurrence should be removed. "
        f"Valid integration IDs: {ids_line}.\n\n"
        "Args:\n"
        "    integration_id: Which integration the series belongs to.\n"
        "    series_ref: Opaque whole-series reference from list_events.\n"
    )
    return _delete_event_series
