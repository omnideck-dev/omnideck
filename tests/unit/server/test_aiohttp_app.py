"""Tests for the public agent-run and application HTTP handlers.

Focused on input validation at the API edge — the chat and stop
endpoints must reject requests without a ``conversation_id`` instead
of silently falling back to a shared "default" conversation.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_runtime import ActiveRunConflictError, UnknownActiveRunError
from server._agent_run_routes import (
    chat_handler,
    chat_run_events_handler,
    delete_nudge_handler,
    list_nudges_handler,
    nudge_handler,
    stop_handler,
)
from server._agent_runtime import ACTIVE_RUN_MANAGER_KEY
from server._ui_routes import index_handler
from sdk.turn import register_nudge_queue, turn_scope, unregister_nudge_queue


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


@pytest.mark.unit
async def test_chat_active_run_conflict_returns_user_friendly_409() -> None:
    """A second start explains the likely tab conflict without runtime jargon."""
    req = _make_request(raw_body=json.dumps({
        "message": "a second message",
        "profile_id": "computron",
        "conversation_id": "abc",
    }))
    manager = MagicMock()
    manager.start = AsyncMock(side_effect=ActiveRunConflictError("conflict"))
    req.app = {ACTIVE_RUN_MANAGER_KEY: manager}

    resp = await chat_handler(req)

    assert resp.status == 409
    body = json.loads(resp.body)
    assert body["error"] == (
        "Another message is already being processed for this conversation, "
        "possibly in another tab or window. Wait for it to finish, then try again."
    )


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


# -- nudge handlers ---------------------------------------------------------


@pytest.mark.unit
async def test_nudge_can_be_listed_and_deleted_while_pending() -> None:
    """The HTTP contract exposes an ID for queue visibility and deletion."""
    agent_id = "root-test"
    register_nudge_queue(agent_id)
    try:
        async with turn_scope(conversation_id="conversation-1"):
            create_req = _make_request(raw_body=json.dumps({
                "message": "keep the API compatible",
                "conversation_id": "conversation-1",
                "agent_id": agent_id,
            }))
            create_resp = await nudge_handler(create_req)

            assert create_resp.status == 200
            created = json.loads(create_resp.body)["nudge"]
            assert created["message"] == "keep the API compatible"
            assert created["agent_id"] == agent_id

            list_req = _make_request(query={
                "conversation_id": "conversation-1",
                "agent_id": agent_id,
            })
            list_resp = await list_nudges_handler(list_req)
            assert json.loads(list_resp.body)["nudges"] == [created]

            delete_req = _make_request(query={
                "conversation_id": "conversation-1",
                "agent_id": agent_id,
            })
            delete_req.match_info = {"nudge_id": created["id"]}
            delete_resp = await delete_nudge_handler(delete_req)
            assert delete_resp.status == 200

            list_resp = await list_nudges_handler(list_req)
            assert json.loads(list_resp.body)["nudges"] == []
    finally:
        unregister_nudge_queue(agent_id)


@pytest.mark.unit
async def test_delete_nudge_returns_404_when_already_consumed() -> None:
    """The delete endpoint makes a drain race explicit and idempotent for UI."""
    req = _make_request(query={
        "conversation_id": "conversation-1",
        "agent_id": "root-missing",
    })
    req.match_info = {"nudge_id": "gone"}

    resp = await delete_nudge_handler(req)

    assert resp.status == 404
    assert json.loads(resp.body)["error"] == "Nudge is no longer pending."


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
