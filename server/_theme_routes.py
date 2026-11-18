"""HTTP routes that deliver the saved theme to the browser application."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiohttp import web

from theme import theme_css, theme_version

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aiohttp.web_request import Request
    from aiohttp.web_response import Response

# The stylesheet changes without its URL changing, so it must revalidate on every use.
_NO_CACHE = {"Cache-Control": "no-cache"}


async def theme_css_handler(_request: Request) -> Response:
    """Serve the stylesheet generated from the saved theme (empty when nothing is overridden)."""
    return web.Response(text=theme_css(), content_type="text/css", headers=_NO_CACHE)


async def theme_version_handler(_request: Request) -> Response:
    """Report the current theme version so the browser can tell whether its copy is stale."""
    return web.json_response({"version": theme_version()}, headers={"Cache-Control": "no-store"})


def register_theme_routes(app: web.Application) -> None:
    """Register the theme stylesheet and version routes."""
    app.router.add_route("GET", "/theme.css", theme_css_handler)
    app.router.add_route("GET", "/api/theme", theme_version_handler)


__all__ = ["register_theme_routes"]
