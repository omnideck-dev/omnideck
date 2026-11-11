"""Tests for server._agent_run_routes.chat_handler's request translation.

The message the user typed reaches AgentRunRequest.message unchanged;
composer skill selections travel separately, by id.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

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
async def test_chat_passes_composer_skill_selections():
    req, manager = _make_request({
        "message": "/joke-teller",
        "conversation_id": "conv-1",
        "skills": [{"id": "4dffecbf8559", "name": "Joke teller"}],
    })
    await routes.chat_handler(req)
    sent = manager.start.call_args[0][0]
    assert [(s.id, s.name) for s in sent.skills] == [("4dffecbf8559", "Joke teller")]
    assert sent.message == "/joke-teller"
