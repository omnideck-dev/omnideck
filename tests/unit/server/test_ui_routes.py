"""Tests for the custom.css route (seeded user style overrides)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from server._ui_routes import custom_css_handler, register_ui_routes
from tools.theme.theme import DEFAULT_CUSTOM_CSS

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _isolate_custom_css(tmp_path: Path, monkeypatch):
    """Point the custom.css path at a temp file, for both the route and the tools."""
    path = tmp_path / "custom.css"
    monkeypatch.setattr("server._ui_routes.custom_css_path", lambda: path)
    monkeypatch.setattr("tools.theme.theme.custom_css_path", lambda: path)
    return path


def _request() -> MagicMock:
    req = MagicMock()
    req.match_info = {}
    req.query = {}
    return req


async def test_custom_css_handler_creates_and_serves_default_file(_isolate_custom_css: Path):
    resp = await custom_css_handler(_request())
    assert _isolate_custom_css.read_text(encoding="utf-8") == DEFAULT_CUSTOM_CSS
    assert resp._path == _isolate_custom_css
    assert resp.headers["Cache-Control"] == "no-cache"


async def test_custom_css_handler_serves_existing_file(_isolate_custom_css: Path):
    _isolate_custom_css.parent.mkdir(parents=True, exist_ok=True)
    _isolate_custom_css.write_text(".foo { color: red; }", encoding="utf-8")
    resp = await custom_css_handler(_request())
    assert resp._path == _isolate_custom_css
    assert _isolate_custom_css.read_text(encoding="utf-8") == ".foo { color: red; }"


async def test_startup_hook_seeds_default_file(_isolate_custom_css: Path):
    app = web.Application()
    register_ui_routes(app)
    assert not _isolate_custom_css.exists()  # registering routes must not touch disk
    async with TestClient(TestServer(app)):
        assert _isolate_custom_css.read_text(encoding="utf-8") == DEFAULT_CUSTOM_CSS


async def test_head_request_exposes_change_validator(_isolate_custom_css: Path):
    """The UI polls HEAD /custom.css; it must be allowed and carry a validator."""
    app = web.Application()
    register_ui_routes(app)
    async with TestClient(TestServer(app)) as client:
        first = await client.head("/custom.css")
        assert first.status == 200
        assert first.headers.get("ETag") or first.headers.get("Last-Modified")
        etag_before = first.headers.get("ETag")

        _isolate_custom_css.write_text(".changed { color: red; }", encoding="utf-8")
        second = await client.head("/custom.css")
        assert second.status == 200
        if etag_before:
            assert second.headers["ETag"] != etag_before
