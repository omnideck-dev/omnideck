"""Tests for chat list changes on the activity stream."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_core.events import AgentEvent, UserMessagePayload
from agent_core.turn import ExecutionResult
from agent_runtime import AgentRunRequest, AgentRuntime, RunSession
from conversations import ConversationChange, archive_conversation, delete_conversation, save_conversation_title
from conversations import _store
from conversations._events_log import EventsLogWriter
from server._activity_messages import ConversationRemovedMessage
from server._conversation_activity import ConversationActivityFeed, conversation_message
from server._run_activity import activity_events

pytestmark = [pytest.mark.unit]


class Runner:
    async def run(self, request: AgentRunRequest, session: RunSession) -> ExecutionResult:
        return ExecutionResult(request.message)


@pytest.fixture()
def conv_root(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "conversations"
    with patch("conversations._store._get_conversations_dir", return_value=root):
        yield root


async def _message(feed) -> dict:
    item = await asyncio.wait_for(anext(feed), 2)
    return item.model_dump(mode="json")


def _start_chat(conversation_id: str, content: str) -> None:
    EventsLogWriter(conversation_id).handle_event(AgentEvent(
        payload=UserMessagePayload(type="user_message", content=content), agent_id="root.agent.1",
    ))


async def test_connecting_sends_a_resync_after_the_run_snapshot(conv_root: Path) -> None:
    runtime = AgentRuntime(Runner())
    feed = activity_events(runtime, [ConversationActivityFeed()])
    try:
        assert (await _message(feed))["type"] == "run_snapshot"
        assert await _message(feed) == {"type": "conversation_resync"}
    finally:
        await feed.aclose()
        await runtime.close()


async def test_chat_changes_reach_the_stream_as_they_happen(conv_root: Path) -> None:
    runtime = AgentRuntime(Runner())
    feed = activity_events(runtime, [ConversationActivityFeed()])
    try:
        await _message(feed)
        await _message(feed)

        _start_chat("chat", "Plan the reunion")
        created = await _message(feed)
        assert created["type"] == "conversation_changed" and created["archived"] is False
        assert created["conversation"]["conversation_id"] == "chat"
        assert created["conversation"]["first_message"] == "Plan the reunion"

        save_conversation_title("chat", "Reunion")
        assert (await _message(feed))["conversation"]["title"] == "Reunion"

        archive_conversation("chat")
        archived = await _message(feed)
        assert archived["archived"] is True and archived["conversation"]["title"] == "Reunion"

        delete_conversation("chat")
        assert await _message(feed) == {"type": "conversation_removed", "conversation_id": "chat"}
    finally:
        await feed.aclose()
        await runtime.close()


async def test_closing_the_stream_stops_observing_the_store(conv_root: Path) -> None:
    runtime = AgentRuntime(Runner())
    feed = activity_events(runtime, [ConversationActivityFeed()])
    try:
        await _message(feed)
        assert len(_store._observers) == 1
    finally:
        await feed.aclose()
        await runtime.close()

    assert _store._observers == []


def test_a_gone_chat_becomes_a_removal_message() -> None:
    assert conversation_message(ConversationChange(conversation_id="chat")) == ConversationRemovedMessage(
        type="conversation_removed", conversation_id="chat",
    )
