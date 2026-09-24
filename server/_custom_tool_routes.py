"""HTTP routes for inspecting and deleting custom tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiohttp import web

from tools.custom_tools.registry import delete_tool, list_tools

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aiohttp.web_request import Request
    from aiohttp.web_response import Response


async def list_custom_tools_handler(_request: Request) -> Response:
    """Return all custom tool definitions as JSON."""
    tools = list_tools()
    data = [
        {
            "id": tool.id,
            "name": tool.name,
            "description": tool.description,
            "type": tool.type,
            "language": tool.language,
            "tags": tool.tags,
            "created_at": tool.created_at,
        }
        for tool in tools
    ]
    return web.json_response(data)


async def delete_custom_tool_handler(request: Request) -> Response:
    """Delete a custom tool by name."""
    name = request.match_info["name"]
    if not delete_tool(name):
        return web.json_response({"error": f"Tool '{name}' not found"}, status=404)
    return web.Response(status=204)


def register_custom_tool_routes(app: web.Application) -> None:
    """Register custom-tool HTTP routes."""
    app.router.add_route("GET", "/api/custom-tools", list_custom_tools_handler)
    app.router.add_route(
        "DELETE",
        "/api/custom-tools/{name}",
        delete_custom_tool_handler,
    )


__all__ = ["register_custom_tool_routes"]
