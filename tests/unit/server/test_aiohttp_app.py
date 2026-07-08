"""Tests for the public HTTP handlers in ``server.aiohttp_app``.

Focused on input validation at the API edge — the chat and stop
endpoints must reject requests without a ``conversation_id`` instead
of silently falling back to a shared "default" conversation.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.aiohttp_app import (
    chat_handler,
    container_file_write_handler,
    index_handler,
    stop_handler,
)


def _make_request(*, raw_body: str | None = None, query: dict | None = None) -> MagicMock:
    """Build a minimal aiohttp.web.Request-ish double."""
    req = MagicMock()
    req.query = query or {}
    if raw_body is not None:
        req.text = AsyncMock(return_value=raw_body)
    return req


def _make_write_request(*, path: str, body: bytes) -> MagicMock:
    """Build a request double for the container-file write handler."""
    req = MagicMock()
    req.match_info = {"path": path}
    req.read = AsyncMock(return_value=body)
    return req


def _patch_home(monkeypatch, home) -> None:
    """Point the write handler's config at a temp home directory."""
    cfg = MagicMock()
    cfg.virtual_computer.home_dir = str(home)
    monkeypatch.setattr("server.aiohttp_app.load_config", lambda: cfg)


# -- chat_handler -----------------------------------------------------------


@pytest.mark.unit
async def test_chat_missing_conversation_id_returns_400() -> None:
    """No conversation_id field → 400 with a clear error message."""
    req = _make_request(raw_body=json.dumps({
        "message": "hi",
        "profile_id": "computron",
    }))
    resp = await chat_handler(req)
    assert resp.status == 400
    body = json.loads(resp.body)
    assert body["error"] == "conversation_id is required."


@pytest.mark.unit
async def test_chat_null_conversation_id_returns_400() -> None:
    """Explicit null conversation_id → 400."""
    req = _make_request(raw_body=json.dumps({
        "message": "hi",
        "profile_id": "computron",
        "conversation_id": None,
    }))
    resp = await chat_handler(req)
    assert resp.status == 400


@pytest.mark.unit
async def test_chat_empty_conversation_id_returns_400() -> None:
    """Empty-string conversation_id → 400."""
    req = _make_request(raw_body=json.dumps({
        "message": "hi",
        "profile_id": "computron",
        "conversation_id": "",
    }))
    resp = await chat_handler(req)
    assert resp.status == 400


@pytest.mark.unit
async def test_chat_missing_message_returns_400() -> None:
    """Pre-existing behavior preserved: empty message also rejected."""
    req = _make_request(raw_body=json.dumps({
        "message": "   ",
        "profile_id": "computron",
        "conversation_id": "abc",
    }))
    resp = await chat_handler(req)
    assert resp.status == 400
    body = json.loads(resp.body)
    assert body["error"] == "Message field is required."


# -- stop_handler -----------------------------------------------------------


@pytest.mark.unit
async def test_stop_missing_conversation_id_returns_400() -> None:
    """No conversation_id query param → 400."""
    req = _make_request(query={})
    resp = await stop_handler(req)
    assert resp.status == 400
    body = json.loads(resp.body)
    assert body["error"] == "conversation_id is required."


@pytest.mark.unit
async def test_stop_empty_conversation_id_returns_400() -> None:
    """Empty conversation_id query value → 400."""
    req = _make_request(query={"conversation_id": ""})
    resp = await stop_handler(req)
    assert resp.status == 400


# -- index_handler ----------------------------------------------------------


# -- container_file_write_handler -------------------------------------------


@pytest.mark.unit
async def test_write_overwrites_existing_file(monkeypatch, tmp_path) -> None:
    """A PUT to an existing home file replaces its bytes and returns ok."""
    _patch_home(monkeypatch, tmp_path)
    target = tmp_path / "notes.md"
    target.write_text("old")

    req = _make_write_request(path="notes.md", body=b"# new content")
    resp = await container_file_write_handler(req)

    assert resp.status == 200
    assert json.loads(resp.body)["ok"] is True
    assert target.read_text() == "# new content"


@pytest.mark.unit
async def test_write_rejects_path_traversal(monkeypatch, tmp_path) -> None:
    """A path escaping the home jail is forbidden and never written."""
    home = tmp_path / "home"
    home.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("keep")
    _patch_home(monkeypatch, home)

    req = _make_write_request(path="../secret.txt", body=b"hacked")
    resp = await container_file_write_handler(req)

    assert resp.status == 403
    assert outside.read_text() == "keep"


@pytest.mark.unit
async def test_write_missing_file_returns_404(monkeypatch, tmp_path) -> None:
    """The route edits existing sources; a missing target is a 404, not a create."""
    _patch_home(monkeypatch, tmp_path)

    req = _make_write_request(path="does-not-exist.txt", body=b"x")
    resp = await container_file_write_handler(req)

    assert resp.status == 404
    assert not (tmp_path / "does-not-exist.txt").exists()


@pytest.mark.unit
async def test_index_handler_sets_no_cache_header(monkeypatch, tmp_path) -> None:
    """The SPA entry point must revalidate so deploys pick up new hashed assets."""
    ui_dist = tmp_path / "dist"
    ui_dist.mkdir()
    (ui_dist / "index.html").write_text("<html></html>")
    monkeypatch.setattr("server.aiohttp_app.UI_DIST_DIR", ui_dist)

    resp = await index_handler(_make_request())

    assert resp.headers["Cache-Control"] == "no-cache"

