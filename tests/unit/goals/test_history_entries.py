"""Who made each history entry, which run it belongs to, and the app's sentences."""

import pytest

from agent_runtime._goal_events import goal_transition_event
from goals import GoalQuestionChange, GoalStore

from tests.unit.goals.support import (
    ask, bind, chat_turn, choose, claim_wake, completed, create, failed, future, goal_tools, root_context, scheduled,
    waiting, with_plan,
)


@pytest.fixture
def store(tmp_path):
    return GoalStore(tmp_path / "session-goals")


def newest(store, goal):
    return store.read_history(goal.id)["entries"][0]


def all_entries(store, goal):
    return list(reversed(store.read_history(goal.id)["entries"]))


def transitions(store, goal):
    events = [goal_transition_event(goal.id, entry) for entry in all_entries(store, goal)]
    return [event.payload.data.kind for event in events if event is not None]


async def test_update_goal_tool_records_agent_actor_and_run(store):
    goal = create(store)
    claim_wake(store, goal)
    tools = goal_tools(store, goal)
    with bind(root_context()):
        await tools["read_goal"]()
        assert await tools["update_goal"](summary="The pavilion costs $80 a day.") == "Saved."
    entry = newest(store, goal)
    assert entry["kind"] == "summary"
    assert entry["actor"] == "agent" and entry["claim_id"] == "claim"
    assert entry["summary"] != "Goal edited"


def test_user_edit_records_user_actor_without_a_run(store):
    goal = create(store)
    store.update(goal.id, goal.revision, objective="Plan the family reunion in June")
    entry = newest(store, goal)
    assert entry["summary"] == "Changed the objective."
    assert entry["actor"] == "user" and entry["claim_id"] is None


def test_user_edit_during_a_run_is_not_tagged_with_that_run(store):
    goal = create(store)
    claim_wake(store, goal)
    store.update(goal.id, store.get(goal.id).revision, summary="Budget is $500.")
    entry = newest(store, goal)
    assert entry["actor"] == "user" and entry["claim_id"] is None


def test_run_note_is_its_own_entry_and_a_repeated_note_is_kept(store):
    goal = with_plan(store, create(store))
    claim_wake(store, goal)
    choose(store, goal, action="continue", note="Called the parks office.")
    store.finish_run(goal.id, "claim", "run-1", "success")
    claim_wake(store, goal, "second")
    choose(store, goal, "second", action="continue", note="Called the parks office.")
    notes = [entry for entry in all_entries(store, goal) if entry["kind"] == "note"]
    assert [entry["summary"] for entry in notes] == ["Called the parks office."] * 2
    assert [entry["claim_id"] for entry in notes] == ["claim", "second"]
    assert all(entry["actor"] == "agent" for entry in notes)


def test_failed_run_records_one_error_transition(store):
    goal = failed(store, create(store), "Rate limit reached (429).")
    entry = newest(store, goal)
    assert entry["kind"] == "state"
    assert entry["summary"] == "The run stopped with an error."
    assert entry["actor"] == "system" and entry["claim_id"] == "setup"
    assert entry["data"]["after"]["next"] == {"kind": "error", "message": "Rate limit reached (429)."}
    kinds = transitions(store, goal)
    assert kinds.count("error") == 1
    assert "waiting" not in kinds


def test_stopped_wake_run_is_recorded_as_the_user_stopping_it(store):
    goal = create(store)
    claim_wake(store, goal)
    store.finish_run(goal.id, "claim", "run-1", "stopped")
    entry = newest(store, goal)
    assert entry["summary"] == "Stopped the run."
    assert entry["actor"] == "user" and entry["claim_id"] == "claim"


def test_wake_run_without_choice_records_that_the_agent_did_not_choose(store):
    goal = create(store)
    claim_wake(store, goal)
    store.finish_run(goal.id, "claim", "run-1", "success")
    entry = newest(store, goal)
    assert entry["summary"] == "The agent stopped without choosing what to do next."
    assert entry["actor"] == "system"
    assert entry["data"]["before"]["next"]["kind"] == "wake"
    assert entry["data"]["after"] == {"next": {"kind": "wait", "question_ids": []}, "paused": False}


def test_chat_turn_that_changes_nothing_adds_no_entry(store):
    goal = waiting(store, create(store))
    count = store.get(goal.id).history_count
    chat_turn(store, goal)
    store.bind_run(goal.id, "turn", "run-1")
    store.finish_run(goal.id, "turn", "run-1", "success")
    assert store.get(goal.id).history_count == count


def test_interrupted_wake_is_recorded_by_the_app_in_the_run_group(store):
    goal = create(store)
    claim_wake(store, goal)
    GoalStore(store._base).recover_claims()
    entry = newest(store, goal)
    assert entry["summary"] == "The run was interrupted. It will run again."
    assert entry["actor"] == "system" and entry["claim_id"] == "claim"


def test_state_sentences_for_user_controls(store):
    goal = scheduled(store, create(store), at="2099-01-02T15:00:00+00:00")
    assert newest(store, goal)["summary"].startswith("Scheduled the next run for ")
    store.pause(goal.id)
    assert newest(store, goal)["summary"] == "Paused the goal."
    assert newest(store, goal)["data"]["after"]["paused"] is True
    store.resume(goal.id)
    assert newest(store, goal)["summary"] == "Resumed the goal."
    store.run(goal.id)
    assert newest(store, goal)["summary"] == "Started a run now."
    store.cancel(goal.id)
    assert newest(store, goal)["summary"] == "Cancelled the goal."
    store.reopen(goal.id)
    assert newest(store, goal)["summary"] == "Reopened the goal."
    assert {entry["actor"] for entry in all_entries(store, goal)[-5:]} == {"user"}


def test_agent_sentences_for_next_actions(store):
    goal = with_plan(store, create(store))
    claim_wake(store, goal)
    choose(store, goal, action="continue")
    assert newest(store, goal)["summary"] == "Continued with the next step."
    choose(store, goal, action="schedule", at=future())
    assert newest(store, goal)["summary"].startswith("Scheduled the next run for ")
    choose(store, goal, action="complete", outcome="Booked.")
    assert newest(store, goal)["summary"] == "Completed the goal."


def test_transition_kinds_for_the_conversation_timeline(store):
    goal = with_plan(store, create(store))
    claim_wake(store, goal)
    choose(store, goal, action="schedule", at=future())
    store.finish_run(goal.id, "claim", "run-1", "success")
    store.pause(goal.id)
    store.resume(goal.id)
    store.run(goal.id)
    claim_wake(store, goal, "second")
    store.finish_run(goal.id, "second", "run-2", "success")
    completed(store, goal)
    store.reopen(goal.id)
    store.cancel(goal.id)
    assert transitions(store, goal) == [
        "started", "scheduled", "paused", "resumed", "waiting", "completed", "reopened", "cancelled",
    ]


def test_pause_during_wake_run_emits_paused_transition(store):
    goal = create(store)
    claim_wake(store, goal)
    store.pause(goal.id)
    entry = newest(store, goal)
    assert entry["data"]["after"]["paused"] is True
    assert entry["data"]["after"]["next"]["reason"] == "interrupted"
    assert transitions(store, goal)[-1] == "paused"
    assert entry["summary"] == "Paused the goal."


def test_wait_that_gains_a_question_gets_a_waiting_divider(store):
    goal = create(store)
    claim_wake(store, goal)
    store.finish_run(goal.id, "claim", "run", "success")
    assert transitions(store, goal)[-1] == "waiting"
    waiting(store, goal)
    assert transitions(store, goal)[-2:] == ["waiting", "waiting"]


def test_wait_that_only_loses_answered_questions_gets_no_divider(store):
    goal = create(store)
    waiting(store, goal)
    chat_turn(store, goal, "turn")
    ask(store, goal, "turn", "place", "Where should we meet?")
    choose(store, goal, "turn", action="wait_for_input", question_ids=["day", "place"])
    before = transitions(store, goal)
    current = store.get(goal.id)
    store.update_questions(goal.id, [GoalQuestionChange(id="place", status="resolved")], current.revision, claim_id="turn")
    assert store.get(goal.id).next.question_ids == ["day"]
    assert transitions(store, goal) == before
