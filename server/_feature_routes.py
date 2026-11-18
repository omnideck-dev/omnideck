"""HTTP route handlers for feature flags."""

from aiohttp import web

from config import load_config
from settings import aperture_enabled, custom_apps_enabled, custom_tools_enabled


async def handle_features(_request: web.Request) -> web.Response:
    """Return enabled feature flags for the UI."""
    features = load_config().features
    return web.json_response({
        "desktop": features.desktop,
        "custom_tools": custom_tools_enabled(),
        "custom_apps": custom_apps_enabled(),
        "aperture": aperture_enabled(),
    })


def register_feature_routes(app: web.Application) -> None:
    """Register feature flag routes on the application."""
    app.router.add_route("GET", "/api/features", handle_features)


__all__ = ["register_feature_routes"]
