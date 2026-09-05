"""HTTP route handler for the tool-category catalog.

Read-only: the UI lists tool categories (what a skill can grant) with the tools
each currently grants and, for integration-backed categories, live connection
state.
"""

from __future__ import annotations

import logging

from aiohttp import web

from sdk.skills import tool_categories
from sdk.skills._policy import is_restricted_tool_category

logger = logging.getLogger(__name__)


async def handle_list_tool_categories(_request: web.Request) -> web.Response:
    """Return the gated tool-category catalog with per-category connection state."""
    categories = await tool_categories()
    return web.json_response(
        [
            {
                "id": c.id,
                "label": c.label,
                "description": c.description,
                "tools": [t.__name__ for t in c.tools],
                "tool_count": len(c.tools),
                "connected": c.connected,
            }
            for c in categories.values()
            if not is_restricted_tool_category(c.id)
        ]
    )


def register_tool_category_routes(app: web.Application) -> None:
    """Register the tool-category catalog route."""
    app.router.add_route("GET", "/api/tool-categories", handle_list_tool_categories)


__all__ = ["register_tool_category_routes"]
