"""HTTP routes for serving the browser application's static assets."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web

from config import load_config

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aiohttp.web_request import Request
    from aiohttp.web_response import StreamResponse

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
UI_DIST_DIR = Path(__file__).parent / "ui" / "dist"


def _custom_css_path() -> Path:
    return Path(load_config().settings.home_dir) / "custom.css"


def _ensure_custom_css() -> None:
    """Ship a blank custom.css on disk so users have a stable place for overrides."""
    path = _custom_css_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")


async def custom_css_handler(_request: Request) -> StreamResponse:
    """Serve the user's editable custom.css, creating it blank if missing."""
    _ensure_custom_css()
    return web.FileResponse(_custom_css_path(), headers={"Cache-Control": "no-cache"})


async def _ensure_custom_css_on_startup(_app: web.Application) -> None:
    """Seed the default custom.css once the app actually starts.

    Deferred to on_startup rather than done eagerly in register_ui_routes, so
    constructing an app (e.g. in tests that never start it) doesn't touch the
    state directory — matching how _run_data_migrations defers its own
    settings.home_dir access in server/aiohttp_app.py.
    """
    _ensure_custom_css()


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


async def manifest_handler(_request: Request) -> StreamResponse:
    """Serve the PWA manifest, which the built dist/ root isn't otherwise routed."""
    manifest_path = UI_DIST_DIR / "manifest.webmanifest"
    if not manifest_path.is_file():
        logger.warning("UI manifest not found: %s", manifest_path)
        return web.Response(
            text="<h1>File not found</h1>",
            content_type="text/html",
            status=404,
        )
    return web.FileResponse(manifest_path, headers={"Cache-Control": "no-cache"})


def register_ui_routes(app: web.Application) -> None:
    """Register the SPA entry point and static asset directories."""
    app.router.add_route("GET", "/", index_handler)
    app.router.add_route("GET", "/custom.css", custom_css_handler)
    app.router.add_route("GET", "/manifest.webmanifest", manifest_handler)
    app.on_startup.append(_ensure_custom_css_on_startup)
    if UI_DIST_DIR.exists():
        app.router.add_static("/assets", UI_DIST_DIR / "assets", show_index=False)
    if STATIC_DIR.exists():
        app.router.add_static("/static", STATIC_DIR, show_index=False)


__all__ = ["register_ui_routes"]
