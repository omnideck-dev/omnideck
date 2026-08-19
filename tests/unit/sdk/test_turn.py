"""Unit tests for turn lifecycle management.

These tests validate that:
- is_turn_active returns False when no turn_scope is active
- is_turn_active returns True inside a turn_scope
- Per-agent nudge queuing and draining works
- Nudge queue is cleaned up on unregister
"""

from __future__ import annotations

import asyncio

import pytest

from sdk.events import AgentEvent, ContentPayload, TurnEndPayload, publish_event
from sdk.turn import (
    StopRequestedError,
    check_stop,
    drain_nudges,
    is_turn_active,
    queue_nudge,
    register_nudge_queue,
    request_stop,
    turn_scope,
    unregister_nudge_queue,
)


@pytest.mark.unit
def test_is_turn_active_outside_context() -> None:
    """is_turn_active returns False when no turn_scope is active."""
    assert is_turn_active("nonexistent") is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_is_turn_active_inside_context() -> None:
    """is_turn_active returns True while turn_scope is active."""
    async with turn_scope(conversation_id="test-sid"):
        assert is_turn_active("test-sid") is True
    assert is_turn_active("test-sid") is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_turn_scope_registers_caller_owned_stop_event() -> None:
    """SDK and application stop requests share one caller-owned signal."""
    stop_event = asyncio.Event()

    async with turn_scope(
        conversation_id="external-stop",
        stop_event=stop_event,
    ):
        request_stop("external-stop")
        assert stop_event.is_set()
        with pytest.raises(StopRequestedError):
            check_stop()


@pytest.mark.unit
def test_queue_and_drain_nudges() -> None:
    """Queued nudges are returned by drain_nudges and cleared."""
    register_nudge_queue("agent-1")
    try:
        queue_nudge("agent-1", "hello")
        queue_nudge("agent-1", "world")
        result = drain_nudges("agent-1")
        assert result == ["hello", "world"]
        assert drain_nudges("agent-1") == []
    finally:
        unregister_nudge_queue("agent-1")


@pytest.mark.unit
def test_drain_nudges_without_agent_id() -> None:
    """drain_nudges returns empty list when no agent_id is given."""
    assert drain_nudges() == []


@pytest.mark.unit
def test_nudge_queue_cleaned_up_on_unregister() -> None:
    """Nudge queue is removed when unregister_nudge_queue is called."""
    register_nudge_queue("agent-cleanup")
    queue_nudge("agent-cleanup", "msg")
    unregister_nudge_queue("agent-cleanup")
    assert drain_nudges("agent-cleanup") == []


@pytest.mark.unit
def test_queue_nudge_noop_without_registration() -> None:
    """queue_nudge is a no-op when no queue is registered for that ID."""
    queue_nudge("no-such-agent", "should be dropped")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_turn_scope_emits_one_final_turn_end() -> None:
    """turn_scope owns the single final turn_end event for a user turn."""
    from sdk.context import ConversationHistory

    captured: list[AgentEvent] = []
    history = ConversationHistory(conversation_id="test-sid")
    history.subscribe(captured.append)

    async with turn_scope(history, conversation_id="test-sid"):
        publish_event(AgentEvent(payload=ContentPayload(type="content", content="during turn")))

    assert [event.payload.type for event in captured] == ["content", "turn_end"]
    assert isinstance(captured[-1].payload, TurnEndPayload)
