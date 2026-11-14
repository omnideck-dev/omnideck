"""Goal creation, user edits, revisions and the in-memory index of unfinished goals."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json

import pytest

from goals import GoalConflictError, GoalRevisionError, GoalStateError, GoalStep, GoalStepChange, GoalStore

from tests.unit.goals.support import completed, create, failed, future, scheduled, waiting, with_plan


@pytest.fixture
def store(tmp_path):
    return GoalStore(tmp_path / "session-goals")


def test_constructor_initializes_file_store_without_creating_goals(tmp_path):
    path = tmp_path / "goals"
    store = GoalStore(path)
    assert store.list() == []
    assert path.is_dir()
    assert list(path.iterdir()) == []


def test_new_goal_is_saved_with_a_planned_wake_due_now(store):
    goal = create(store)
    saved = json.loads((store._base / goal.id / "goal.json").read_text())
    assert saved["next"]["kind"] == "wake"
    assert saved["next"]["reason"] == "planned"
    assert saved["paused"] is False and saved["claim"] is None and saved["note"] == ""
    assert not {"status", "status_reason", "next_action", "resume_at", "wake_id", "known_facts"} & saved.keys()
    fresh = GoalStore(store._base)
    assert fresh.current("chat") == goal
    assert fresh.due() == [goal]
    with pytest.raises(GoalConflictError):
        create(fresh)


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


def test_user_plan_edit_and_dependency_validation_keep_saved_plan(store):
    goal = create(store)
    plan = [
        GoalStep(id="guests", title="Collect the guest list"),
        GoalStep(id="venue", title="Book the park pavilion", depends_on=["guests"]),
    ]
    updated = store.update(goal.id, goal.revision, plan=plan)
    assert [step.id for step in updated.plan] == ["guests", "venue"]
    with pytest.raises(GoalRevisionError):
        store.update(goal.id, goal.revision, plan=[])
    for invalid in (
        [GoalStep(id="one", title="One", depends_on=["missing"])],
        [GoalStep(id="one", title="One", depends_on=["one"])],
        [GoalStep(id="one", title="One"), GoalStep(id="one", title="Two")],
    ):
        with pytest.raises(ValueError):
            store.update(goal.id, updated.revision, plan=invalid)
    assert store.get(goal.id) == updated


def test_revision_error_is_a_conflict_error():
    assert issubclass(GoalRevisionError, GoalConflictError)


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


def test_update_needs_a_change_and_one_kind_of_plan_input(store):
    goal = create(store)
    with pytest.raises(ValueError, match="Change"):
        store.update(goal.id, goal.revision)
    with pytest.raises(ValueError, match="either"):
        store.update(goal.id, goal.revision, plan=[], step_changes=[])
    assert store.get(goal.id) == goal


def test_update_cannot_forge_ownership(store):
    goal = create(store)
    with pytest.raises(GoalConflictError):
        store.update(goal.id, goal.revision, claim_id="forged", summary="Unauthorized change")
    with pytest.raises(TypeError):
        store.update(goal.id, goal.revision, next={"kind": "done", "outcome": "Forged"})
    assert store.get(goal.id) == goal


def test_step_changes_merge_into_the_saved_plan(store):
    goal = with_plan(store, create(store),
                     GoalStep(id="guests", title="Collect the guest list", notes="12 replies so far"),
                     GoalStep(id="venue", title="Book the park pavilion", depends_on=["guests"]))
    updated = store.update(goal.id, goal.revision, step_changes=[
        GoalStepChange(id="guests", status="done"),
        GoalStepChange(id="food", title="Order the food", before="venue"),
    ])
    assert [step.id for step in updated.plan] == ["guests", "food", "venue"]
    assert updated.plan[0].notes == "12 replies so far"
    assert updated.plan[0].status == "done"
    with pytest.raises(ValueError, match="needs a title"):
        store.update(goal.id, updated.revision, step_changes=[GoalStepChange(id="music")])
    assert store.get(goal.id) == updated


def test_ended_goal_refuses_edits_and_resume(store):
    goal = create(store)
    store.cancel(goal.id)
    with pytest.raises(GoalStateError):
        store.update(goal.id, store.get(goal.id).revision, summary="Late progress")
    with pytest.raises(GoalStateError):
        store.resume(goal.id)
    with pytest.raises(GoalStateError):
        store.pause(goal.id)


def test_deleting_a_conversation_removes_only_its_goals(store):
    goal = create(store)
    store.cancel(goal.id)
    create(store)
    unrelated = create(store, "other")
    store.delete_for_conversation("chat")
    assert store.history("chat") == []
    assert store.list() == [unrelated]
    assert store.current("chat") is None
    assert [item.id for item in store.wakes()] == [unrelated.id]


def test_due_and_wakes_list_only_unpaused_unclaimed_wakes(store):
    due = create(store, "due")
    later = scheduled(store, create(store, "later"))
    paused = create(store, "paused")
    store.pause(paused.id)
    asking = waiting(store, create(store, "asking"))
    broken = failed(store, create(store, "broken"))
    done = completed(store, create(store, "done"))
    assert [goal.id for goal in store.due()] == [due.id]
    assert {goal.id for goal in store.wakes()} == {due.id, later.id}
    assert {goal.id for goal in store.due(future(days=2))} == {due.id, later.id}
    assert not {paused.id, asking.id, broken.id, done.id} & {goal.id for goal in store.due(future(days=2))}


def test_due_does_not_read_ended_goals(store, monkeypatch):
    for index in range(5):
        completed(store, create(store, f"done-{index}"))
    open_goal = create(store, "open")
    fresh = GoalStore(store._base)
    reads: list[Path] = []
    original = Path.read_text

    def counted(path, *args, **kwargs):
        reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted)
    fresh.load()
    # Startup reads each saved goal once to find the unfinished ones.
    assert len(reads) == 6
    reads.clear()
    for _ in range(20):
        assert [goal.id for goal in fresh.due()] == [open_goal.id]
        assert [goal.id for goal in fresh.wakes()] == [open_goal.id]
    assert reads == []


def test_index_follows_changes_from_another_store_on_the_same_folder(store):
    goal = create(store)
    other = GoalStore(store._base)
    other.pause(goal.id)
    assert store.due() == []
    other.resume(goal.id)
    assert [item.id for item in store.due()] == [goal.id]
