"""Tests for server._agent_run_routes.chat_handler's request translation.

The message the user typed reaches AgentRunRequest.message unchanged;
composer selections travel separately, as typed context items.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

import server._agent_run_routes as routes


def _make_request(body: dict):
    req = MagicMock()
    req.text = AsyncMock(return_value=json.dumps(body))
    manager = MagicMock()
    manager.start = AsyncMock(return_value=MagicMock(run_id="run-1"))
    req.app = {routes.AGENT_RUNTIME_KEY: manager}
    return req, manager


@pytest.fixture(autouse=True)
def _stub_stream_events(monkeypatch):
    # chat_handler always follows a successful start with stream_events, which
    # needs a real aiohttp response; these tests only care what reaches
    # manager.start, so stub the streaming tail out.
    monkeypatch.setattr(routes, "stream_events", AsyncMock(return_value="streamed"))


@pytest.mark.unit
async def test_plain_message_passes_through_unchanged():
    req, manager = _make_request({
        "message": "just a plain message",
        "conversation_id": "conv-1",
    })
    await routes.chat_handler(req)
    sent = manager.start.call_args[0][0]
    assert sent.message == "just a plain message"


@pytest.mark.unit
async def test_composer_token_text_reaches_the_run_request_verbatim():
    req, manager = _make_request({
        "message": "/does-not-exist do something",
        "conversation_id": "conv-1",
    })
    await routes.chat_handler(req)
    sent = manager.start.call_args[0][0]
    assert sent.message == "/does-not-exist do something"


@pytest.mark.unit
async def test_chat_passes_composer_context():
    req, manager = _make_request({
        "message": "/joke-teller",
        "conversation_id": "conv-1",
        "context": [{"type": "skill", "skill_id": "4dffecbf8559", "name": "Joke teller"}],
    })
    await routes.chat_handler(req)
    sent = manager.start.call_args[0][0]
    assert [(c.skill_id, c.name) for c in sent.context] == [("4dffecbf8559", "Joke teller")]
    assert sent.message == "/joke-teller"


@pytest.mark.unit
async def test_chat_rejects_an_unknown_context_type():
    req, manager = _make_request({
        "message": "hi",
        "conversation_id": "conv-1",
        "context": [{"type": "agent", "agent_id": "writer", "name": "Writer"}],
    })
    # The app's error middleware turns this into a 400.
    with pytest.raises(ValidationError):
        await routes.chat_handler(req)
    manager.start.assert_not_called()


@pytest.mark.unit
async def test_chat_rejects_too_many_context_items():
    req, manager = _make_request({
        "message": "hi",
        "conversation_id": "conv-1",
        "context": [{"type": "skill", "skill_id": f"s{i}", "name": f"S{i}"} for i in range(21)],
    })
    with pytest.raises(ValidationError):
        await routes.chat_handler(req)
    manager.start.assert_not_called()
