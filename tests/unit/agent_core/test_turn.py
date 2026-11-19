"""Agent core scopes bind inputs; application sessions own run state and terminal events."""

import asyncio

import pytest

from agent_core.control import ExecutionControl, get_execution_control
from agent_core.context import ConversationHistory
from agent_core.events import AgentEvent, ContentPayload, publish_event
from agent_core.turn import StopRequestedError, check_stop, get_conversation_id, turn_scope


async def test_scope_binds_and_restores_conversation_identity():
    assert get_conversation_id() is None
    async with turn_scope(conversation_id="outer"):
        assert get_conversation_id() == "outer"
        async with turn_scope(conversation_id="inner"):
            assert get_conversation_id() == "inner"
        assert get_conversation_id() == "outer"
    assert get_conversation_id() is None


async def test_scope_uses_caller_owned_stop_event():
    signal = asyncio.Event()
    async with turn_scope(conversation_id="controlled", stop_event=signal):
        signal.set()
        with pytest.raises(StopRequestedError):
            check_stop()
    assert get_execution_control() is None


def test_nudges_belong_to_each_control_and_are_consumed_once():
    first, second = ExecutionControl(), ExecutionControl()
    first.nudge("hello")
    first.nudge("world")
    assert second.drain_nudges() == []
    assert [message.content for message in first.drain_nudges()] == ["hello", "world"]
    assert first.drain_nudges() == []


def test_each_nudge_gets_an_id_carried_on_its_user_message():
    control = ExecutionControl()
    nudge_id = control.nudge("hello")
    (message,) = control.drain_nudges()
    assert message.nudge_id == nudge_id
    assert message.is_nudge
    assert control.nudge("again") != nudge_id


def test_remove_nudge_works_before_reading_and_fails_after():
    control = ExecutionControl()
    removed, kept = control.nudge("never mind"), control.nudge("keep this")
    assert control.remove_nudge(removed)
    assert not control.remove_nudge(removed)
    assert [message.content for message in control.drain_nudges()] == ["keep this"]
    assert not control.remove_nudge(kept)


def test_return_unread_takes_every_waiting_nudge_and_closes_the_inbox():
    control = ExecutionControl()
    first, second = control.nudge("one"), control.nudge("two")
    assert [message.nudge_id for message in control.return_unread()] == [first, second]
    assert control.nudges == []
    with pytest.raises(ValueError):
        control.nudge("late")


async def test_scope_publishes_supplied_events_without_synthesizing_run_completion():
    history = ConversationHistory(conversation_id="scope")
    events = []
    history.subscribe(events.append)
    async with turn_scope(history, conversation_id="scope"):
        publish_event(AgentEvent(payload=ContentPayload(type="content", content="during scope")))
    assert [e.payload.type for e in events] == ["content"]
