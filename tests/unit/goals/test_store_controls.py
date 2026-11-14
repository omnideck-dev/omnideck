"""User controls: pause, resume, run now, retry, cancel and reopen."""

import pytest

from goals import GoalConflictError, GoalStateError, GoalStore

from tests.unit.goals.support import (
    chat_turn, choose, claim_wake, completed, create, failed, future, scheduled, waiting, with_plan,
)


@pytest.fixture
def store(tmp_path):
    return GoalStore(tmp_path / "session-goals")


def test_pause_and_resume_keep_future_wake(store):
    goal = scheduled(store, create(store))
    paused = store.pause(goal.id)
    assert paused.paused and paused.next == goal.next
    resumed = store.resume(goal.id)
    assert not resumed.paused
    assert resumed.next == goal.next
    assert store.due() == []
    assert [item.id for item in store.due(future(days=2))] == [goal.id]


def test_pause_and_resume_keep_wait(store):
    goal = waiting(store, create(store))
    store.pause(goal.id)
    resumed = store.resume(goal.id)
    assert resumed.next == goal.next
    assert resumed.next.question_ids == ["day"]


def test_resume_keeps_error(store):
    goal = failed(store, create(store))
    store.pause(goal.id)
    resumed = store.resume(goal.id)
    assert resumed.next == goal.next
    assert resumed.next.kind == "error"


def test_resume_does_not_queue_a_wake(store):
    goal = waiting(store, create(store))
    store.pause(goal.id)
    store.resume(goal.id)
    assert store.due() == []
    assert store.wakes() == []


def test_pause_during_wake_run_marks_wake_interrupted(store):
    goal = create(store)
    claim_wake(store, goal)
    paused = store.pause(goal.id)
    assert paused.claim is None
    assert paused.next.id == goal.next.id and paused.next.at == goal.next.at
    assert paused.next.reason == "interrupted"
    assert store.due() == []
    store.resume(goal.id)
    assert [item.id for item in store.due()] == [goal.id]


def test_pause_during_chat_turn_keeps_next(store):
    goal = waiting(store, create(store))
    chat_turn(store, goal)
    paused = store.pause(goal.id)
    assert paused.claim is None
    assert paused.next == goal.next


def test_late_write_from_run_ended_by_pause_is_refused(store):
    goal = with_plan(store, create(store))
    claim_wake(store, goal)
    store.pause(goal.id)
    with pytest.raises(GoalConflictError, match="no longer owns"):
        choose(store, goal, action="continue")
    with pytest.raises(GoalConflictError):
        store.update(goal.id, store.get(goal.id).revision, claim_id="claim", actor="agent", summary="Late")
    assert store.finish_run(goal.id, "claim", "run", "success") is None


def test_due_skips_paused_goals(store):
    goal = create(store)
    store.pause(goal.id)
    assert store.due() == []
    assert store.wakes() == []
    assert store.claim(goal.id, goal.next.id, "claim") is None


def test_chat_turn_on_paused_goal_can_schedule(store):
    goal = with_plan(store, create(store))
    store.pause(goal.id)
    chat_turn(store, goal)
    friday = future(days=3)
    choose(store, goal, "turn", action="schedule", at=friday)
    finished = store.finish_run(goal.id, "turn", "run-1", "success")
    assert finished.paused
    assert finished.next.kind == "wake" and finished.next.reason == "planned"
    assert store.due(future(days=4)) == []
    store.resume(goal.id)
    assert [item.id for item in store.due(future(days=4))] == [goal.id]


def test_pause_twice_and_resume_unpaused_are_refused(store):
    goal = create(store)
    with pytest.raises(GoalStateError, match="not paused"):
        store.resume(goal.id)
    store.pause(goal.id)
    with pytest.raises(GoalStateError, match="already paused"):
        store.pause(goal.id)


def test_run_moves_future_wake_to_now(store):
    goal = scheduled(store, create(store))
    ran = store.run(goal.id)
    assert ran.next.id == goal.next.id
    assert ran.next.reason == "run_now"
    assert ran.revision == goal.revision + 1
    assert [item.id for item in store.due()] == [goal.id]
    entry = store.read_history(goal.id)["entries"][0]
    assert entry["summary"] == "Started a run now." and entry["actor"] == "user"


def test_run_from_error_sets_retry_wake(store):
    goal = failed(store, create(store))
    ran = store.run(goal.id)
    assert ran.next.kind == "wake" and ran.next.reason == "retry"
    assert [item.id for item in store.due()] == [goal.id]
    assert store.read_history(goal.id)["entries"][0]["summary"] == "Retried the goal."


def test_run_refused_while_paused(store):
    goal = scheduled(store, create(store))
    store.pause(goal.id)
    with pytest.raises(GoalStateError, match="Resume"):
        store.run(goal.id)


def test_run_refused_while_running(store):
    goal = create(store)
    claim_wake(store, goal)
    with pytest.raises(GoalStateError, match="already running"):
        store.run(goal.id)


def test_run_refused_while_waiting_and_on_ended_goal(store):
    goal = waiting(store, create(store))
    with pytest.raises(GoalStateError, match="waiting"):
        store.run(goal.id)
    done = completed(store, create(store, "finished"))
    with pytest.raises(GoalStateError, match="ended"):
        store.run(done.id)


def test_run_checks_the_expected_revision(store):
    goal = scheduled(store, create(store))
    with pytest.raises(GoalConflictError):
        store.run(goal.id, expected_revision=goal.revision - 1)


def test_cancel_ends_the_goal_and_clears_pause_and_claim(store):
    goal = create(store)
    claim_wake(store, goal)
    store.pause(goal.id)
    cancelled = store.cancel(goal.id)
    assert cancelled.next.kind == "cancelled"
    assert not cancelled.paused and cancelled.claim is None
    assert store.current("chat") is None
    with pytest.raises(GoalStateError):
        store.cancel(goal.id)


def test_reopen_waits_with_no_questions_and_keeps_plan_and_history(store):
    goal = with_plan(store, create(store))
    store.update(goal.id, store.get(goal.id).revision, summary="Pavilion costs $80.")
    done = completed(store, goal)
    reopened = store.reopen(goal.id)
    assert reopened.next.kind == "wait" and reopened.next.question_ids == []
    assert reopened.plan == done.plan and reopened.summary == done.summary
    assert reopened.note == "" and not reopened.paused and reopened.claim is None
    assert reopened.history_count == done.history_count + 1
    assert store.read_history(goal.id)["entries"][0]["summary"] == "Reopened the goal."
    assert store.current("chat").id == goal.id
    assert store.due() == []


def test_reopen_refused_when_not_ended(store):
    goal = create(store)
    with pytest.raises(GoalStateError, match="not ended"):
        store.reopen(goal.id)


def test_reopen_refused_when_chat_has_a_newer_unfinished_goal(store):
    old = completed(store, create(store))
    create(store, objective="Plan the holiday dinner")
    with pytest.raises(GoalConflictError, match="unfinished goal"):
        store.reopen(old.id)
