"""Tests for the public agent-run and application HTTP handlers.

Focused on input validation at the API edge — the chat and stop
endpoints must reject requests without a ``conversation_id`` instead
of silently falling back to a shared "default" conversation.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_runtime import UnknownActiveRunError
from server._agent_run_routes import (
    chat_handler,
    chat_run_events_handler,
    stop_handler,
)
from server._agent_runtime import ACTIVE_RUN_MANAGER_KEY
from server._ui_routes import index_handler


def _make_request(*, raw_body: str | None = None, query: dict | None = None) -> MagicMock:
    """Build a minimal aiohttp.web.Request-ish double."""
    req = MagicMock()
    req.query = query or {}
    if raw_body is not None:
        req.text = AsyncMock(return_value=raw_body)
    return req


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


@pytest.mark.unit
async def test_stop_targets_active_run_manager() -> None:
    """Stop sets the manager-owned signal rather than an HTTP-task signal."""
    manager = MagicMock()
    req = _make_request(query={"conversation_id": "conversation-1"})
    req.app = {ACTIVE_RUN_MANAGER_KEY: manager}

    resp = await stop_handler(req)

    assert resp.status == 200
    manager.request_stop.assert_called_once_with("conversation-1")


# -- run events handler ----------------------------------------------------


@pytest.mark.unit
async def test_run_events_rejects_non_integer_cursor() -> None:
    """Reconnect cursors must be unambiguous integer sequence numbers."""
    req = _make_request(query={"after": "later"})
    req.match_info = {"run_id": "run-1"}

    resp = await chat_run_events_handler(req)

    assert resp.status == 400


@pytest.mark.unit
async def test_run_events_returns_404_for_completed_run() -> None:
    """Unknown and already-pruned runs tell the client to reload persistence."""
    manager = MagicMock()
    manager.subscribe.side_effect = UnknownActiveRunError("gone")
    req = _make_request(query={"after": "3"})
    req.match_info = {"run_id": "run-1"}
    req.app = {ACTIVE_RUN_MANAGER_KEY: manager}

    resp = await chat_run_events_handler(req)

    assert resp.status == 404
    manager.subscribe.assert_called_once_with("run-1", after_seq=3)


# -- index_handler ----------------------------------------------------------


@pytest.mark.unit
async def test_index_handler_sets_no_cache_header(monkeypatch, tmp_path) -> None:
    """The SPA entry point must revalidate so deploys pick up new hashed assets."""
    ui_dist = tmp_path / "dist"
    ui_dist.mkdir()
    (ui_dist / "index.html").write_text("<html></html>")
    monkeypatch.setattr("server._ui_routes.UI_DIST_DIR", ui_dist)

    resp = await index_handler(_make_request())

    assert resp.headers["Cache-Control"] == "no-cache"
