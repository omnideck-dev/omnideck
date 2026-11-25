"""Tests for chat change notifications from the conversation store."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_core.events import AgentEvent, IterationPayload, UserMessagePayload
from conversations import ConversationChange
from conversations._events_log import EventsLogWriter
from conversations._store import (
    archive_conversation,
    delete_conversation,
    ensure_conversation,
    save_conversation_folder,
    save_conversation_pinned,
    save_conversation_profile,
    save_conversation_title,
    save_preview_state,
    subscribe_conversation_changes,
    unarchive_conversation,
)

pytestmark = [pytest.mark.unit]


@pytest.fixture()
def conv_root(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "conversations"
    with patch("conversations._store._get_conversations_dir", return_value=root):
        yield root


@pytest.fixture()
def changes(conv_root: Path) -> Iterator[list[ConversationChange]]:
    seen: list[ConversationChange] = []
    unsubscribe = subscribe_conversation_changes(seen.append)
    yield seen
    unsubscribe()


def _user_message(content: str, agent_id: str = "root.agent.1") -> AgentEvent:
    return AgentEvent(
        payload=UserMessagePayload(type="user_message", content=content), agent_id=agent_id, depth=0,
    )


def _started_chat(conversation_id: str = "chat") -> None:
    EventsLogWriter(conversation_id).handle_event(_user_message("Plan the reunion"))


def test_first_root_message_reports_the_new_chat_with_its_first_message(changes) -> None:
    _started_chat()

    assert len(changes) == 1
    change = changes[0]
    assert change.conversation_id == "chat" and change.archived is False
    assert change.summary is not None
    assert change.summary.first_message == "Plan the reunion" and change.summary.turn_count == 1


def test_each_root_turn_reports_the_new_turn_count(changes) -> None:
    writer = EventsLogWriter("chat")
    writer.handle_event(_user_message("first"))
    writer.handle_event(_user_message("second"))

    assert [change.summary.turn_count for change in changes if change.summary] == [1, 2]


def test_sub_agent_messages_and_other_events_report_nothing(changes) -> None:
    writer = EventsLogWriter("chat")
    writer.handle_event(_user_message("delegated", agent_id="root.agent.1.child.2"))
    writer.handle_event(AgentEvent(
        payload=IterationPayload(type="iteration", iteration_index=0, content="ok"), agent_id="root.agent.1",
    ))

    assert changes == []


def test_title_pin_and_folder_changes_report_the_updated_summary(changes) -> None:
    _started_chat()
    changes.clear()

    save_conversation_title("chat", "Reunion")
    save_conversation_pinned("chat", True)
    save_conversation_folder("chat", "family")

    summaries = [change.summary for change in changes]
    assert [s.title for s in summaries if s] == ["Reunion", "Reunion", "Reunion"]
    assert [s.pinned for s in summaries if s] == [False, True, False]
    assert summaries[-1] is not None and summaries[-1].folder_id == "family"


def test_profile_preview_and_skill_saves_report_nothing(changes) -> None:
    _started_chat()
    changes.clear()

    save_conversation_profile("chat", "assistant")
    save_preview_state("chat", {"tabs": []})

    assert changes == []


def test_ensure_conversation_reports_the_titled_chat_once(changes) -> None:
    ensure_conversation("goal-chat", title="Renew the passports", profile_id="assistant")

    assert len(changes) == 1
    assert changes[0].summary is not None and changes[0].summary.title == "Renew the passports"


def test_archive_and_restore_report_which_list_the_chat_belongs_to(changes) -> None:
    _started_chat()
    changes.clear()

    archive_conversation("chat")
    unarchive_conversation("chat")

    assert [(change.archived, change.summary is not None) for change in changes] == [(True, True), (False, True)]


def test_delete_reports_the_chat_as_gone(changes) -> None:
    _started_chat()
    changes.clear()

    delete_conversation("chat")

    assert changes == [ConversationChange(conversation_id="chat")]


def test_actions_on_missing_chats_report_nothing(changes) -> None:
    assert archive_conversation("ghost") is False
    assert unarchive_conversation("ghost") is False
    assert delete_conversation("ghost") is False
    assert changes == []


def test_nested_chats_such_as_routine_runs_are_never_reported(changes) -> None:
    EventsLogWriter("routines/r1/run1/task1").handle_event(_user_message("Check the weather"))

    assert changes == []


def test_a_failing_observer_does_not_stop_the_others(conv_root: Path) -> None:
    def broken(_change: ConversationChange) -> None:
        raise RuntimeError("boom")

    seen: list[ConversationChange] = []
    stop_broken = subscribe_conversation_changes(broken)
    stop_seen = subscribe_conversation_changes(seen.append)
    try:
        _started_chat()
    finally:
        stop_broken()
        stop_seen()

    assert len(seen) == 1


def test_unsubscribed_observers_hear_nothing(conv_root: Path) -> None:
    seen: list[ConversationChange] = []
    subscribe_conversation_changes(seen.append)()

    _started_chat()

    assert seen == []
