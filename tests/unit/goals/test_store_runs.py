"""Run ownership: claims, the end-of-run rule, failures, restarts and revisions."""

import pytest

from goals import GoalConflictError, GoalStateError, GoalStore

from tests.unit.goals.support import (
    ask, chat_turn, choose, claim_wake, completed, create, failed, future, past, scheduled, waiting, with_plan,
)


@pytest.fixture
def store(tmp_path):
    return GoalStore(tmp_path / "session-goals")


def test_claim_keeps_the_wake_in_place(store):
    goal = create(store)
    claimed = claim_wake(store, goal)
    assert claimed.next == goal.next
    assert claimed.claim.id == "claim" and claimed.claim.wake_id == goal.next.id
    assert store.due() == []
    assert store.claim(goal.id, goal.next.id, "duplicate") is None


def test_claim_refuses_a_future_wake_another_wake_or_a_paused_goal(store):
    goal = scheduled(store, create(store))
    assert store.claim(goal.id, goal.next.id, "early") is None
    assert store.claim(goal.id, "another-wake", "stale", now=future(days=2)) is None
    store.pause(goal.id)
    assert store.claim(goal.id, goal.next.id, "paused", now=future(days=2)) is None
    store.resume(goal.id)
    assert store.claim(goal.id, goal.next.id, "on-time", now=future(days=2)) is not None


def test_claim_for_turn_refuses_ended_and_already_claimed_goals(store):
    goal = create(store)
    claim_wake(store, goal)
    assert store.claim_for_turn(goal.id, "turn") is None
    store.finish_run(goal.id, "claim", "run", "success")
    assert store.claim_for_turn(goal.id, "turn") is not None
    store.finish_run(goal.id, "turn", "run", "success")
    done = completed(store, create(store, "finished"))
    assert store.claim_for_turn(done.id, "turn") is None


def test_wake_run_without_choice_waits_for_user(store):
    goal = create(store)
    claim_wake(store, goal)
    finished = store.finish_run(goal.id, "claim", "run-1", "success")
    assert finished.next.kind == "wait" and finished.next.question_ids == []
    assert finished.claim is None
    assert finished.last_run_id == "run-1"
    assert store.due() == []


def test_wake_run_with_choice_keeps_choice(store):
    goal = with_plan(store, create(store))
    claim_wake(store, goal)
    tomorrow = future()
    chosen = choose(store, goal, action="schedule", at=tomorrow)
    finished = store.finish_run(goal.id, "claim", "run-1", "success")
    assert finished.next == chosen.next
    assert finished.next.kind == "wake" and finished.next.id != goal.next.id
    assert finished.claim is None


def test_stopped_wake_run_waits_for_user(store):
    goal = create(store)
    claim_wake(store, goal)
    finished = store.finish_run(goal.id, "claim", "run-1", "stopped")
    assert finished.next.kind == "wait" and finished.next.question_ids == []
    assert finished.claim is None


def test_chat_turn_keeps_waiting_goal_waiting(store):
    goal = waiting(store, create(store))
    chat_turn(store, goal)
    finished = store.finish_run(goal.id, "turn", "run-1", "success")
    assert finished.next == goal.next
    assert finished.revision == goal.revision


def test_chat_turn_leaves_due_wake_to_run_after(store):
    goal = create(store)
    chat_turn(store, goal)
    assert store.due() == []
    finished = store.finish_run(goal.id, "turn", "run-1", "success")
    assert finished.next == goal.next
    assert [item.id for item in store.due()] == [goal.id]


def test_failed_wake_run_without_choice_sets_error(store):
    goal = create(store)
    claim_wake(store, goal)
    finished = store.finish_run(goal.id, "claim", "run-1", "error", error="Rate limit reached (429).")
    assert finished.next.kind == "error"
    assert finished.next.message == "Rate limit reached (429)."
    assert finished.claim is None


def test_failed_wake_run_without_message_uses_plain_error(store):
    goal = create(store)
    claim_wake(store, goal)
    finished = store.finish_run(goal.id, "claim", "run-1", "error")
    assert finished.next.message == "The goal run failed."


@pytest.mark.parametrize("choice", ["schedule", "wait", "done"])
def test_failed_wake_run_keeps_agent_choice(store, choice):
    goal = with_plan(store, create(store))
    claim_wake(store, goal)
    if choice == "schedule":
        chosen = choose(store, goal, action="schedule", at=future())
    elif choice == "wait":
        ask(store, goal)
        chosen = choose(store, goal, action="wait_for_input", question_ids=["day"])
    else:
        chosen = choose(store, goal, action="complete", outcome="Pavilion booked and confirmed by email.")
    finished = store.finish_run(goal.id, "claim", "run-1", "error", error="Provider unavailable")
    assert finished.next == chosen.next
    assert finished.claim is None


def test_failed_chat_turn_keeps_goal(store):
    goal = waiting(store, create(store))
    chat_turn(store, goal)
    finished = store.finish_run(goal.id, "turn", "run-1", "error", error="Provider unavailable")
    assert finished.next == goal.next
    assert finished.revision == goal.revision


def test_chat_turn_keeps_error_without_choice(store):
    goal = failed(store, create(store))
    chat_turn(store, goal)
    finished = store.finish_run(goal.id, "turn", "run-1", "success")
    assert finished.next == goal.next
    assert finished.next.kind == "error"


def test_chat_turn_choice_replaces_error(store):
    goal = with_plan(store, failed(store, create(store)))
    chat_turn(store, goal)
    choose(store, goal, "turn", action="continue")
    finished = store.finish_run(goal.id, "turn", "run-1", "success")
    assert finished.next.kind == "wake" and finished.next.reason == "planned"
    assert [item.id for item in store.due()] == [goal.id]


def test_due_skips_error_goals(store):
    goal = failed(store, create(store))
    assert store.due(future(days=30)) == []
    assert store.wakes() == []
    assert store.get(goal.id).next.kind == "error"


def test_claim_bind_and_finish_without_change_keep_revision(store):
    goal = waiting(store, create(store))
    history = store.get(goal.id).history_count
    claimed = chat_turn(store, goal)
    bound = store.bind_run(goal.id, "turn", "run-1")
    finished = store.finish_run(goal.id, "turn", "run-1", "success")
    assert claimed.revision == bound.revision == finished.revision == goal.revision
    assert finished.history_count == history
    assert bound.last_run_id == "run-1"


def test_release_keeps_revision_and_wake(store):
    goal = create(store)
    claim_wake(store, goal)
    released = store.release(goal.id, "claim")
    assert released.claim is None
    assert released.revision == goal.revision
    assert released.next == goal.next
    assert [item.id for item in store.due()] == [goal.id]


def test_release_and_finish_by_another_claim_do_nothing(store):
    goal = create(store)
    claim_wake(store, goal)
    assert store.release(goal.id, "other") is None
    assert store.finish_run(goal.id, "other", "run", "success") is None
    assert store.bind_run(goal.id, "other", "run") is None
    assert store.get(goal.id).claim.id == "claim"


def test_wake_change_raises_revision(store):
    goal = with_plan(store, create(store))
    claim_wake(store, goal)
    chosen = choose(store, goal, action="continue")
    assert chosen.revision == goal.revision + 1


def test_recover_claims_marks_held_wake_interrupted(store):
    goal = create(store)
    claim_wake(store, goal)
    restarted = GoalStore(store._base)
    recovered = restarted.recover_claims()
    assert [item.id for item in recovered] == [goal.id]
    current = restarted.get(goal.id)
    assert current.claim is None
    assert current.next.id == goal.next.id and current.next.at == goal.next.at
    assert current.next.reason == "interrupted"
    assert current.revision == goal.revision + 1
    assert [item.id for item in restarted.due()] == [goal.id]
    assert restarted.recover_claims() == []


def test_recover_claims_keeps_the_agent_choice_of_an_interrupted_run(store):
    goal = with_plan(store, create(store))
    claim_wake(store, goal)
    chosen = choose(store, goal, action="schedule", at=future())
    GoalStore(store._base).recover_claims()
    current = store.get(goal.id)
    assert current.next == chosen.next
    assert current.claim is None
    assert current.revision == chosen.revision


def test_recover_claims_leaves_chat_turn_goal_unchanged(store):
    goal = waiting(store, create(store))
    chat_turn(store, goal)
    GoalStore(store._base).recover_claims()
    current = store.get(goal.id)
    assert current.claim is None
    assert current.next == goal.next
    assert current.revision == goal.revision


def test_choose_needs_the_current_claim(store):
    goal = with_plan(store, create(store))
    with pytest.raises(GoalConflictError, match="no longer owns"):
        choose(store, goal, action="continue")
    claim_wake(store, goal)
    with pytest.raises(GoalConflictError):
        choose(store, goal, "someone-else", action="continue")


def test_choose_refuses_continue_and_schedule_without_an_open_step(store):
    goal = create(store)
    claim_wake(store, goal)
    for fields in ({"action": "continue"}, {"action": "schedule", "at": future()}):
        with pytest.raises(GoalStateError, match="Mark the step"):
            choose(store, goal, **fields)
    assert store.get(goal.id).revision == goal.revision


def test_choose_refuses_a_past_time_and_names_now(store):
    goal = with_plan(store, create(store))
    claim_wake(store, goal)
    with pytest.raises(ValueError, match="It is now"):
        choose(store, goal, action="schedule", at=past())
    with pytest.raises(ValueError, match="timezone"):
        choose(store, goal, action="schedule", at="2099-01-01T12:00:00")


def test_wait_needs_open_questions_and_no_unread_answers(store):
    from goals import GoalAnswerSubmission

    goal = create(store)
    claim_wake(store, goal)
    with pytest.raises(GoalStateError, match="open questions"):
        choose(store, goal, action="wait_for_input", question_ids=["day"])
    asked = ask(store, goal)
    store.save_answers("chat", GoalAnswerSubmission(goal_id=goal.id, answers=[
        {"question_id": "day", "question_revision": asked.questions[0].revision, "answer": "June 14"},
    ]))
    with pytest.raises(GoalConflictError, match="New answers"):
        choose(store, goal, action="wait_for_input", question_ids=["day"])
    with pytest.raises(ValueError, match="once"):
        choose(store, goal, action="wait_for_input", question_ids=["day", "day"])


def test_complete_ends_the_goal_and_keeps_the_note(store):
    goal = create(store)
    claim_wake(store, goal)
    done = choose(store, goal, action="complete", outcome="Booked the pavilion for June 14.",
                  note="Booked it and got the confirmation email.")
    assert done.ended
    assert done.next.outcome == "Booked the pavilion for June 14."
    assert done.note == "Booked it and got the confirmation email."
    assert store.current("chat") is None
    finished = store.finish_run(goal.id, "claim", "run-1", "success")
    assert finished.next == done.next and finished.claim is None


def test_interrupt_without_held_wake_only_clears_claim(store):
    goal = waiting(store, create(store))
    chat_turn(store, goal)
    interrupted = store.interrupt(goal.id)
    assert interrupted.claim is None
    assert interrupted.revision == goal.revision
    assert interrupted.next == goal.next
