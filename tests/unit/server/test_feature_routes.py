"""Tests for the feature state exposed to the frontend."""

from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from server._feature_routes import register_feature_routes

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("setting_name", ["custom_apps", "custom_tools"])
@pytest.mark.parametrize("enabled", [False, True])
async def test_user_feature_comes_from_settings(
    monkeypatch, setting_name: str, enabled: bool,
) -> None:
    """User-controlled feature flags reflect their persisted setting."""
    monkeypatch.setattr(
        "server._feature_routes.load_config",
        lambda: SimpleNamespace(features=SimpleNamespace(
            image_generation=False,
            music_generation=False,
            desktop=False,
            visual_grounding=False,
        )),
    )
    monkeypatch.setattr(
        f"server._feature_routes.{setting_name}_enabled",
        lambda: enabled,
    )

    app = web.Application()
    register_feature_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        response = await client.get("/api/features")
        assert response.status == 200
        assert (await response.json())[setting_name] is enabled
    finally:
        await client.close()
