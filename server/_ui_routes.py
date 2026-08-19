"""HTTP routes for serving the browser application's static assets."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aiohttp.web_request import Request
    from aiohttp.web_response import StreamResponse

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
UI_DIST_DIR = Path(__file__).parent / "ui" / "dist"


async def index_handler(_request: Request) -> StreamResponse:
    """Serve a revalidated SPA entry point so deployments load current assets."""
    index_path = UI_DIST_DIR / "index.html"
    if not index_path.is_file():
        logger.warning("UI index not found: %s", index_path)
        return web.Response(
            text="<h1>File not found</h1>",
            content_type="text/html",
            status=404,
        )
    return web.FileResponse(index_path, headers={"Cache-Control": "no-cache"})


def register_ui_routes(app: web.Application) -> None:
    """Register the SPA entry point and static asset directories."""
    app.router.add_route("GET", "/", index_handler)
    if UI_DIST_DIR.exists():
        app.router.add_static("/assets", UI_DIST_DIR / "assets", show_index=False)
    if STATIC_DIR.exists():
        app.router.add_static("/static", STATIC_DIR, show_index=False)


__all__ = ["register_ui_routes"]
