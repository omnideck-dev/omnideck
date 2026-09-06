"""Tests for NudgeHook event emission."""

from __future__ import annotations

from typing import Any, List

import pytest

from sdk.context import ConversationHistory
from sdk.events import (
    AgentEvent,
    UserMessagePayload,
    agent_span,
    reset_current_conversation,
    set_current_conversation,
)
from sdk.hooks._nudge_hook import NudgeHook
from sdk.agent_capabilities import AgentCapabilities
from sdk.turn import turn_scope
from sdk.turn._nudge_queue import queue_nudge


class _FakeHistory:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def append(self, msg: dict[str, Any]) -> None:
        self.messages.append(msg)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nudge_hook_publishes_user_message_event_when_nudges_present():
    captured: List[AgentEvent] = []

    async def _handler(evt: AgentEvent) -> None:
        captured.append(evt)

    hook = NudgeHook()
    history = _FakeHistory()
    # Use a real conversation as the publish target so nudge events fan out.
    conv = ConversationHistory(conversation_id="c1")
    conv.subscribe(_handler)

    async with turn_scope():
        conv_token = set_current_conversation(conv)
        try:
            async with agent_span("Test", agent_capabilities=AgentCapabilities([])) as agent_id:
                queue_nudge(agent_id, "first nudge")
                queue_nudge(agent_id, "second nudge")
                await hook.before_model(history, iteration=1, agent_name="Test")
        finally:
            reset_current_conversation(conv_token)
            await conv.drain_observers()

    nudge_events = [e.payload for e in captured if isinstance(e.payload, UserMessagePayload)]
    assert len(nudge_events) == 1
    assert nudge_events[0].content == "first nudge\n\nsecond nudge"
    assert nudge_events[0].attachments == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nudge_hook_emits_nothing_when_queue_empty():
    captured: List[AgentEvent] = []

    async def _handler(evt: AgentEvent) -> None:
        captured.append(evt)

    hook = NudgeHook()
    history = _FakeHistory()
    conv = ConversationHistory(conversation_id="c1")
    conv.subscribe(_handler)

    async with turn_scope():
        conv_token = set_current_conversation(conv)
        try:
            async with agent_span("Test", agent_capabilities=AgentCapabilities([])):
                await hook.before_model(history, iteration=1, agent_name="Test")
        finally:
            reset_current_conversation(conv_token)
            await conv.drain_observers()

    assert not any(isinstance(e.payload, UserMessagePayload) for e in captured)
    assert history.messages == []
