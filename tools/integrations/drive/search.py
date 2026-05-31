"""Agent tool: search a Drive by file name (and optionally mime type)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from config import load_config
from integrations import broker_client
from tools.integrations.drive._format import format_entry

logger = logging.getLogger(__name__)


async def drive_search(
    integration_id: str,
    name_contains: str,
    mime_type: str = "",
    limit: int = 50,
) -> str:
    """Search a Drive for entries whose name contains a substring.

    Args:
        integration_id: Which Drive integration to search.
        name_contains: Case-insensitive substring to match against file/folder
            names. Required.
        mime_type: Optional exact mime-type filter (e.g. ``"application/pdf"``).
        limit: Maximum entries to return (default 50).

    Returns:
        Plain text — one entry per line with the entry's handle in brackets.
        For backends without a server-side search (iCloud Drive), large drives
        may return a ``truncated`` flag — narrow the query if that happens.
    """
    app_sock = load_config().integrations.app_sock_path
    args: dict[str, Any] = {"name_contains": name_contains, "limit": limit}
    if mime_type:
        args["mime_type"] = mime_type
    try:
        result = await broker_client.call(
            integration_id, "drive_search", args, app_sock_path=app_sock,
        )
    except broker_client.IntegrationNotConnected:
        return f"Integration {integration_id!r} is not connected."
    except broker_client.IntegrationError as exc:
        logger.warning(
            "drive_search(%r, %r) failed: %s", integration_id, name_contains, exc,
        )
        return f"Failed to search Drive: {exc}"

    entries = result.get("entries", [])
    truncated = bool(result.get("truncated", False))
    if not entries:
        return f"No matches for {name_contains!r}."
    lines = [format_entry(e) for e in entries]
    header = f"{len(lines)} match(es) for {name_contains!r}"
    if truncated:
        header += " (more results may exist — narrow your query to see them)"
    return header + ":\n" + "\n".join(lines)


def build_drive_search_tool(integration_ids: Iterable[str]) -> Callable[..., Any]:
    ids = sorted(integration_ids)
    ids_line = ", ".join(repr(i) for i in ids) if ids else "(none registered)"

    async def _drive_search(
        integration_id: str,
        name_contains: str,
        mime_type: str = "",
        limit: int = 50,
    ) -> str:
        return await drive_search(integration_id, name_contains, mime_type, limit)

    _drive_search.__name__ = drive_search.__name__
    _drive_search.__doc__ = (
        "Search a Drive for entries whose name contains a substring. "
        f"Valid integration IDs: {ids_line}.\n\n"
        "Args:\n"
        "    integration_id: Which Drive integration to search.\n"
        "    name_contains: Case-insensitive substring to match against\n"
        "        file/folder names.\n"
        "    mime_type: Optional exact mime-type filter (e.g.\n"
        "        'application/pdf').\n"
        "    limit: Maximum entries to return (default 50).\n\n"
        "Returns:\n"
        "    Plain text — one entry per line; each line ends with [handle] so\n"
        "    you can pass the handle to other drive_* tools. If the backend\n"
        "    can't search server-side (iCloud Drive) and the drive is large,\n"
        "    the result may be truncated — the header will say so.\n"
    )
    return _drive_search
