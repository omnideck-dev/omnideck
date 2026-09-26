"""Tests for server._agent_run_routes.chat_handler's request translation.

Composer-token enrichment (`/skill`, `@agent /skill`) is NOT applied here —
it runs downstream as a model-facing-only view transform, so the raw text
the user typed reaches AgentRunRequest.message unchanged and is what gets
stored/displayed.
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
