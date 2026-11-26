"""Execution control: a shared stop signal and an execution-local message inbox."""

import pytest

from agent_core.control import ExecutionControl


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
