"""HTTP routes for controlling the shared desktop environment."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiohttp import web

from tools.desktop._exec import DesktopExecError
from tools.desktop._lifecycle import start_desktop

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aiohttp.web_request import Request
    from aiohttp.web_response import Response


async def desktop_start_handler(_request: Request) -> Response:
    """Start the desktop environment and return its status."""
    try:
        await start_desktop()
        return web.json_response({"running": True})
    except DesktopExecError as exc:
        return web.json_response(
            {"running": False, "error": str(exc)},
            status=503,
        )


def register_desktop_routes(app: web.Application) -> None:
    """Register desktop-control HTTP routes."""
    app.router.add_route("POST", "/api/desktop/start", desktop_start_handler)


__all__ = ["register_desktop_routes"]
