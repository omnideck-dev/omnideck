"""Tests for experimental Custom App discovery and execution."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from server._custom_app_routes import custom_app_roots, register_custom_app_routes

pytestmark = pytest.mark.unit


def test_only_discovers_apps_from_the_user_home(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    config = SimpleNamespace(virtual_computer=SimpleNamespace(home_dir=home))
    monkeypatch.setattr("server._custom_app_routes.load_config", lambda: config)

    assert custom_app_roots() == (home / "apps",)


def _write_app(root: Path, slug: str = "example") -> Path:
    app = root / slug
    (app / "web").mkdir(parents=True)
    (app / "omnideck.json").write_text(json.dumps({
        "title": "Example App",
        "description": "A test Custom App.",
        "icon": "bi-stars",
    }), encoding="utf-8")
    (app / "web" / "index.html").write_text("<h1>Custom App</h1>", encoding="utf-8")
    (app / "app.py").write_text(
        "from omnideck_apps import action\n\n"
        "@action\n"
        "def greet(name: str):\n"
        "    return {'message': f'Hello, {name}!'}\n\n"
        "def helper():\n"
        "    return 'not exposed'\n",
        encoding="utf-8",
    )
    return app


@pytest.fixture()
async def custom_apps_client(tmp_path: Path, monkeypatch) -> TestClient:
    root = tmp_path / "apps"
    root.mkdir()
    _write_app(root)
    monkeypatch.setattr("server._custom_app_routes.custom_app_roots", lambda: (root,))
    settings_state = {"custom_apps_enabled": True, "home_app_slug": None}
    monkeypatch.setattr("server._custom_app_routes.custom_apps_enabled", lambda: True)
    monkeypatch.setattr("server._custom_app_routes.load_settings", lambda: dict(settings_state))

    def save_test_settings(update: dict) -> dict:
        settings_state.update(update)
        return dict(settings_state)

    monkeypatch.setattr("server._custom_app_routes.save_settings", save_test_settings)
    app = web.Application()
    app["custom_apps_test_settings"] = settings_state
    app["custom_apps_test_root"] = root
    register_custom_app_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        yield client
    finally:
        await client.close()


async def test_lists_valid_custom_apps(custom_apps_client: TestClient) -> None:
    response = await custom_apps_client.get("/api/custom-apps")
    assert response.status == 200
    assert await response.json() == {
        "home_app_slug": None,
        "apps": [{
            "slug": "example",
            "title": "Example App",
            "description": "A test Custom App.",
            "icon": "bi-stars",
            "has_actions": True,
        }],
    }


async def test_loads_app_symlinked_from_monorepo(custom_apps_client: TestClient) -> None:
    apps_root = custom_apps_client.app["custom_apps_test_root"]
    monorepo = apps_root.parent / "custom-apps-repo"
    monorepo.mkdir()
    source = _write_app(monorepo, "source-app")
    (apps_root / "linked-app").symlink_to(source, target_is_directory=True)

    listed = await custom_apps_client.get("/api/custom-apps")
    linked = next(app for app in (await listed.json())["apps"] if app["slug"] == "linked-app")
    assert linked["title"] == "Example App"

    frame = await custom_apps_client.get("/api/custom-apps/linked-app/frame/")
    assert frame.status == 200
    assert await frame.text() == "<h1>Custom App</h1>"

    invoked = await custom_apps_client.post(
        "/api/custom-apps/linked-app/invoke/greet",
        json={"args": {"name": "Ada"}},
    )
    assert invoked.status == 200
    assert await invoked.json() == {"ok": True, "result": {"message": "Hello, Ada!"}}


async def test_ignores_broken_and_looping_app_symlinks(custom_apps_client: TestClient) -> None:
    apps_root = custom_apps_client.app["custom_apps_test_root"]
    (apps_root / "broken-app").symlink_to(apps_root.parent / "missing", target_is_directory=True)
    (apps_root / "loop-app").symlink_to(apps_root / "loop-app", target_is_directory=True)

    response = await custom_apps_client.get("/api/custom-apps")
    assert [app["slug"] for app in (await response.json())["apps"]] == ["example"]


async def test_sets_and_clears_home_app(custom_apps_client: TestClient) -> None:
    set_response = await custom_apps_client.put("/api/custom-apps/home", json={"slug": "example"})
    assert set_response.status == 200
    assert await set_response.json() == {"ok": True, "home_app_slug": "example"}

    listed = await custom_apps_client.get("/api/custom-apps")
    assert (await listed.json())["home_app_slug"] == "example"

    clear_response = await custom_apps_client.delete("/api/custom-apps/home")
    assert clear_response.status == 200
    assert await clear_response.json() == {"ok": True, "home_app_slug": None}


async def test_rejects_missing_home_app(custom_apps_client: TestClient) -> None:
    response = await custom_apps_client.put("/api/custom-apps/home", json={"slug": "missing"})
    assert response.status == 404
    assert (await response.json())["error"]["code"] == "APP_NOT_FOUND"


async def test_serves_frontend_and_invokes_python_action(custom_apps_client: TestClient) -> None:
    frame = await custom_apps_client.get("/api/custom-apps/example/frame/")
    assert frame.status == 200
    assert await frame.text() == "<h1>Custom App</h1>"
    content_security_policy = frame.headers["Content-Security-Policy"]
    assert content_security_policy == "frame-ancestors 'self'"
    assert "default-src" not in content_security_policy

    response = await custom_apps_client.post(
        "/api/custom-apps/example/invoke/greet",
        json={"args": {"name": "Ada"}},
    )
    assert response.status == 200
    assert await response.json() == {"ok": True, "result": {"message": "Hello, Ada!"}}


async def test_sdk_exposes_explicit_chat_bridge(custom_apps_client: TestClient) -> None:
    response = await custom_apps_client.get("/api/custom-apps/sdk.js")
    assert response.status == 200
    source = await response.text()
    assert "omnideck:chat-open" in source
    assert "omnideck:chat-compose" in source
    assert "omnideck:download" in source
    assert "event.origin !== shellOrigin" in source


async def test_rejects_invalid_action_arguments(custom_apps_client: TestClient) -> None:
    response = await custom_apps_client.post(
        "/api/custom-apps/example/invoke/greet",
        json={"args": {}},
    )
    assert response.status == 400
    body = await response.json()
    assert body["error"]["code"] == "INVALID_ARGUMENTS"


async def test_does_not_expose_undecorated_functions(custom_apps_client: TestClient) -> None:
    response = await custom_apps_client.post(
        "/api/custom-apps/example/invoke/helper",
        json={"args": {}},
    )
    assert response.status == 404
    assert (await response.json())["error"]["code"] == "ACTION_NOT_FOUND"


async def test_does_not_serve_files_outside_web_root(custom_apps_client: TestClient) -> None:
    response = await custom_apps_client.get("/api/custom-apps/example/frame/../app.py")
    assert response.status == 404


async def test_feature_flag_blocks_every_surface(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "apps"
    root.mkdir()
    _write_app(root)
    monkeypatch.setattr("server._custom_app_routes.custom_app_roots", lambda: (root,))
    monkeypatch.setattr("server._custom_app_routes.custom_apps_enabled", lambda: False)
    app = web.Application()
    register_custom_app_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        list_response = await client.get("/api/custom-apps")
        frame_response = await client.get("/api/custom-apps/example/frame/")
        invoke_response = await client.post("/api/custom-apps/example/invoke/greet", json={"args": {"name": "Ada"}})
        assert {list_response.status, frame_response.status, invoke_response.status} == {403}
    finally:
        await client.close()
