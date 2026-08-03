"""HTTP routes for inspecting and managing agent memory."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from aiohttp import web

from tools.memory import forget as forget_memory
from tools.memory import load_memory, set_key_hidden

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aiohttp.web_request import Request
    from aiohttp.web_response import Response


async def list_memory_handler(_request: Request) -> Response:
    """Return all stored memories and the set of hidden keys."""
    entries = load_memory()
    return web.json_response(
        {
            "entries": {key: entry.value for key, entry in entries.items()},
            "hidden": sorted(key for key, entry in entries.items() if entry.hidden),
        }
    )


async def delete_memory_handler(request: Request) -> Response:
    """Delete a memory entry by key."""
    key = request.match_info["key"]
    result = await forget_memory(key)
    if result.get("status") == "not_found":
        return web.json_response({"error": f"Memory key '{key}' not found"}, status=404)
    return web.Response(status=204)


async def set_memory_hidden_handler(request: Request) -> Response:
    """Set the hidden flag for a memory entry."""
    key = request.match_info["key"]
    if key not in load_memory():
        return web.json_response({"error": f"Memory key '{key}' not found"}, status=404)
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    set_key_hidden(key, bool(body.get("hidden", False)))
    return web.Response(status=204)


def register_memory_routes(app: web.Application) -> None:
    """Register memory-management HTTP routes."""
    app.router.add_route("GET", "/api/memory", list_memory_handler)
    app.router.add_route("DELETE", "/api/memory/{key}", delete_memory_handler)
    app.router.add_route(
        "POST",
        "/api/memory/{key}/hidden",
        set_memory_hidden_handler,
    )


__all__ = ["register_memory_routes"]
