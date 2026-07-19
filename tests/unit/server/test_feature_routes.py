"""Tests for the feature state exposed to the frontend."""

from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from server._feature_routes import register_feature_routes

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("enabled", [False, True])
async def test_custom_apps_feature_comes_from_settings(monkeypatch, enabled: bool) -> None:
    monkeypatch.setattr(
        "server._feature_routes.load_config",
        lambda: SimpleNamespace(features=SimpleNamespace(
            image_generation=False,
            music_generation=False,
            desktop=False,
            visual_grounding=False,
            custom_tools=False,
        )),
    )
    monkeypatch.setattr("server._feature_routes.custom_apps_enabled", lambda: enabled)

    app = web.Application()
    register_feature_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        response = await client.get("/api/features")
        assert response.status == 200
        assert (await response.json())["custom_apps"] is enabled
    finally:
        await client.close()
