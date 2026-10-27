"""Tests for the routes that deliver the saved theme to the browser."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from server._theme_routes import register_theme_routes
from server._ui_routes import register_ui_routes
from theme import update_theme

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _theme_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "theme.json"
    monkeypatch.setattr("theme.store.theme_path", lambda: path)
    return path


@pytest.fixture
async def client() -> AsyncIterator[TestClient]:
    app = web.Application()
    register_theme_routes(app)
    register_ui_routes(app)
    async with TestClient(TestServer(app)) as test_client:
        yield test_client


async def test_stylesheet_is_empty_when_nothing_is_overridden(client: TestClient):
    response = await client.get("/theme.css")
    assert response.status == 200
    assert response.content_type == "text/css"
    assert response.headers["Cache-Control"] == "no-cache"
    assert await response.text() == ""


async def test_stylesheet_reflects_saved_overrides_without_a_restart(client: TestClient):
    update_theme(light={"accent": "#7c3aed"}, dark={"canvas": "#000000"}, fonts={"font-body": "Georgia, serif"})

    css = await (await client.get("/theme.css")).text()

    assert ':root:not([data-theme="dark"]) {\n  --accent: #7c3aed;\n}' in css
    assert ':root[data-theme="dark"] {\n  --canvas: #000000;\n}' in css
    assert ":root {\n  --font-body: Georgia, serif;\n}" in css


async def test_version_changes_when_the_theme_changes_and_returns_when_reset(client: TestClient):
    async def version() -> str:
        response = await client.get("/api/theme")
        assert response.status == 200
        assert response.headers["Cache-Control"] == "no-store"
        return (await response.json())["version"]

    pristine = await version()
    update_theme(light={"accent": "#7c3aed"})
    changed = await version()
    update_theme(reset=True)

    assert changed != pristine
    assert await version() == pristine


async def test_hand_written_css_files_are_no_longer_served(client: TestClient, tmp_path: Path):
    """Raw custom.css support is gone; a leftover file is ignored and never reaches the browser."""
    (tmp_path / "custom.css").write_text("body { display: none; }", encoding="utf-8")
    response = await client.get("/custom.css")
    assert response.status == 404
    assert "display: none" not in await response.text()
