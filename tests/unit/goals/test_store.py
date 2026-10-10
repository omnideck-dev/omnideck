"""Durable goal scheduling, plan revisions, and execution ownership."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from goals import GoalConflictError, GoalQuestionChange, GoalStateError, GoalStore


@pytest.fixture
def store(tmp_path):
    return GoalStore(tmp_path / "session-goals")


def create(store, conversation="chat"):
    return store.create(conversation, "Prepare the household schedule", "assistant")


def future():
    return (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()


def claim(store, goal):
    claimed = store.claim(goal.id, goal.wake_id, "claim-1")
    assert claimed is not None
    return claimed


def test_constructor_and_reads_do_not_create_state_directory(tmp_path):
    path = tmp_path / "goals"
    store = GoalStore(path)
    assert store.list() == []
    assert not path.exists()


def test_assignment_is_durable_and_queues_one_immediate_wake(store):
    goal = create(store)
    fresh = GoalStore(store._base)
    assert fresh.current("chat") == goal
    assert fresh.due() == [goal]
    with pytest.raises(GoalConflictError):
        create(fresh)
    claimed = claim(fresh, goal)
    assert claimed.wake_id is None
    assert fresh.due() == []
    assert fresh.claim(goal.id, goal.wake_id, "duplicate") is None


def test_paused_goal_still_occupies_its_conversation_but_ended_goals_are_retained(store):
    first = create(store)
    store.pause(first.id)
    with pytest.raises(GoalConflictError):
        create(store)
    store.cancel(first.id)
    second = create(store)
    assert store.current("chat").id == second.id
    assert len(store.history("chat")) == 2
    assert store.latest("chat").id == second.id


def test_checklist_revision_and_dependency_validation_preserve_saved_plan(store):
    goal = create(store)
    plan = [
        {"id": "gather", "title": "Gather household commitments"},
        {"id": "draft", "title": "Draft the weekly calendar", "depends_on": ["gather"]},
    ]
    updated = store.update(goal.id, goal.revision, plan=plan)
    assert [step.id for step in updated.plan] == ["gather", "draft"]
    with pytest.raises(GoalConflictError):
        store.update(goal.id, goal.revision, plan=[])
    for invalid in (
        [{"id": "one", "title": "One", "depends_on": ["missing"]}],
        [{"id": "one", "title": "One", "depends_on": ["one"]}],
        [{"id": "one", "title": "One"}, {"id": "one", "title": "Two"}],
        [{"id": "one", "title": "One", "depends_on": ["two"]},
         {"id": "two", "title": "Two", "depends_on": ["one"]}],
    ):
        with pytest.raises(ValidationError):
            store.update(goal.id, updated.revision, plan=invalid)
        assert store.get(goal.id) == updated


def test_revision_conflict_is_atomic_between_store_instances(store):
    goal = create(store)
    second = GoalStore(store._base)

    def update(index):
        try:
            return (store if index == 0 else second).update(goal.id, goal.revision, objective=f"Goal {index}")
        except GoalConflictError:
            return None

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(update, range(2)))
    assert sum(result is not None for result in results) == 1
    assert store.get(goal.id).revision == goal.revision + 1


def test_schedule_replaces_wake_atomically_and_requires_zoned_future_time(store):
    goal = claim(store, create(store))
    with pytest.raises(ValueError, match="timezone"):
        store.schedule(goal.id, "2099-01-01T12:00:00", "Wait", "Check")
    with pytest.raises(ValueError, match="future"):
        store.schedule(goal.id, "2000-01-01T12:00:00Z", "Wait", "Check")
    first = store.schedule(goal.id, future(), "Calendar update due", "Read calendar", claim_id="claim-1")
    second = store.schedule(goal.id, "2099-01-01T12:00:00-06:00", "Wait longer", "Read calendar", claim_id="claim-1")
    assert second.resume_at == "2099-01-01T18:00:00+00:00"
    assert second.wake_id != first.wake_id
    assert second.claimed_run_id == "claim-1"
    assert store.due("2100-01-01T00:00:00Z") == []
    store.release(goal.id, "claim-1")
    assert len(store.due("2100-01-01T00:00:00Z")) == 1
    assert store.claim(goal.id, first.wake_id, "stale", now="2100-01-01T00:00:00Z") is None


def test_pause_invalidates_pending_and_claimed_wakes_and_late_owner_writes(store):
    original = create(store)
    claimed = claim(store, original)
    store.pause(claimed.id)
    with pytest.raises(GoalConflictError):
        store.record_progress(claimed.id, "Late write", claim_id="claim-1")
    assert store.release(claimed.id, "claim-1") is None
    assert store.claim(claimed.id, original.wake_id, "late") is None
    assert store.due() == []
    resumed = store.resume(claimed.id)
    assert resumed.wake_id != original.wake_id
    assert len(store.due()) == 1


def test_manual_turn_preserves_future_schedule_without_changing_paused_goals(store):
    goal = create(store)
    scheduled = store.schedule(goal.id, future(), "Wait", "Check calendar")
    manual = store.claim_for_turn(goal.id, "manual")
    assert manual.status == "scheduled"
    assert manual.claimed_wake_id == scheduled.wake_id
    assert manual.wake_id == scheduled.wake_id
    assert store.due("2100-01-01T00:00:00Z") == []
    finished = store.finish_run(goal.id, "manual", "manual-run", "success")
    assert finished.wake_id == scheduled.wake_id
    assert finished.resume_at == scheduled.resume_at
    assert finished.status == "scheduled"
    assert len(store.due("2100-01-01T00:00:00Z")) == 1
    store.pause(goal.id)
    assert store.claim_for_turn(goal.id, "other") is None


def test_manual_turn_consumes_initial_due_wake(store):
    goal = create(store)
    manual = store.claim_for_turn(goal.id, "manual")
    assert manual.status == "active"
    assert manual.wake_id is None
    assert manual.claimed_wake_id == goal.wake_id


def test_manual_turn_can_explicitly_replace_preserved_future_wake(store):
    goal = create(store)
    scheduled = store.schedule(goal.id, future(), "Wait", "Check calendar")
    store.claim_for_turn(goal.id, "manual")
    replacement = store.schedule(goal.id, future(), "Updated timing", "Check new calendar", claim_id="manual")
    assert replacement.wake_id != scheduled.wake_id
    store.update_questions(goal.id, [GoalQuestionChange(id="calendar", question="Which calendar?", status="open")], "", store.get(goal.id).revision, claim_id="manual")
    store.wait_for_input(goal.id, ["calendar"], claim_id="manual")
    assert store.get(goal.id).wake_id is None


def test_aborted_dispatch_requeues_only_unmodified_claim(store):
    original = create(store)
    claim(store, original)
    store.bind_run(original.id, "claim-1", "runtime-1")
    restored = store.requeue_claim(original.id, "claim-1")
    assert restored.wake_id == original.wake_id
    assert restored.claimed_run_id is None
    claimed = store.claim(restored.id, restored.wake_id, "claim-2")
    store.record_progress(claimed.id, "An external action occurred", claim_id="claim-2")
    assert store.requeue_claim(claimed.id, "claim-2") is None


def test_finish_without_disposition_does_not_infer_continuation(store):
    goal = claim(store, create(store))
    result = store.finish_run(goal.id, "claim-1", "runtime-1", "success")
    assert result.status == "active"
    assert result.wake_id is None
    assert result.last_run_id == "runtime-1"
    assert result.claimed_run_id is None
    assert result.revision > goal.revision
    assert store.due() == []
    assert store.finish_run(goal.id, "claim-1", "runtime-1", "success") is None


def test_error_needs_input_but_preserves_explicit_agent_wake(store):
    first = claim(store, create(store))
    failed = store.finish_run(first.id, "claim-1", "run-1", "error", "Provider unavailable")
    assert failed.status == "needs_input"
    assert failed.status_reason == "Provider unavailable"
    second = claim(store, create(store, "second"))
    scheduled = store.schedule(second.id, future(), "Wait", "Check", claim_id="claim-1")
    result = store.finish_run(second.id, "claim-1", "run-2", "error", "Provider unavailable")
    assert result.status == "scheduled"
    assert result.wake_id == scheduled.wake_id


def test_restart_reconciles_interrupted_execution_once_without_overriding_agent_decisions(store):
    interrupted = claim(store, create(store, "interrupted"))
    scheduled = claim(store, create(store, "scheduled"))
    future_goal = store.schedule(scheduled.id, future(), "Wait for response", "Read the response", claim_id="claim-1")
    waiting = claim(store, create(store, "waiting"))
    store.update_questions(waiting.id, [GoalQuestionChange(id="calendar", question="Which calendar?", status="open")], "", waiting.revision, claim_id="claim-1")
    store.wait_for_input(waiting.id, ["calendar"], claim_id="claim-1")
    completed = claim(store, create(store, "completed"))
    store.complete(completed.id, "Delivered the calendar", claim_id="claim-1")
    recovered = GoalStore(store._base)
    assert len(recovered.recover_claims()) == 4
    resumed = recovered.get(interrupted.id)
    assert resumed.wake_id is not None
    assert "external state" in resumed.next_action
    assert recovered.get(scheduled.id).wake_id == future_goal.wake_id
    assert recovered.get(waiting.id).status == "needs_input"
    assert recovered.get(completed.id).status == "completed"
    assert recovered.recover_claims() == []
    assert len(recovered.due()) == 1


def test_generic_update_cannot_forge_status_or_ownership(store):
    goal = create(store)
    with pytest.raises(ValueError):
        store.update(goal.id, goal.revision, status="completed", claimed_run_id="forged")
    assert store.get(goal.id) == goal


def test_cancelled_goal_cannot_resume_and_deletion_removes_history(store):
    goal = create(store)
    store.cancel(goal.id)
    with pytest.raises(GoalStateError):
        store.resume(goal.id)
    create(store)
    unrelated = create(store, "other")
    store.delete_for_conversation("chat")
    assert store.history("chat") == []
    assert store.list() == [unrelated]
