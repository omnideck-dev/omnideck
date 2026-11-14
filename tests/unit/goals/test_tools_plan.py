"""update_goal: plan step changes by ID and the optional summary."""

import json

import pytest

from goals import GoalStep, GoalStore

from tests.unit.goals.support import bind, call, claim_wake, create, goal_tools, root_context, with_plan


@pytest.fixture
def planned(tmp_path):
    store = GoalStore(tmp_path / "goals")
    goal = with_plan(
        store, create(store),
        GoalStep(id="guests", title="Collect the guest list", status="in_progress", notes="12 replies so far"),
        GoalStep(id="book_pavilion", title="Book the park pavilion", depends_on=["guests"]),
        GoalStep(id="food", title="Order the food", depends_on=["guests", "book_pavilion"]),
    )
    claim_wake(store, goal)
    tools = goal_tools(store, goal)
    context = root_context()
    return store, goal, context, tools


async def update(context, tools, **arguments):
    with bind(context):
        await tools["read_goal"]()
        return await call(tools["update_goal"], **arguments)


async def test_plan_status_change_keeps_other_fields(planned):
    store, goal, context, tools = planned
    assert await update(context, tools, plan=[{"id": "book_pavilion", "status": "done"}]) == "Saved."
    saved = store.get(goal.id).plan
    assert saved[1] == goal.plan[1].model_copy(update={"status": "done"})
    assert saved[0] == goal.plan[0] and saved[2] == goal.plan[2]


async def test_new_step_goes_before_named_step(planned):
    store, goal, context, tools = planned
    await update(context, tools, plan=[{"id": "deposit", "title": "Pay the pavilion deposit", "before": "food"}])
    assert [step.id for step in store.get(goal.id).plan] == ["guests", "book_pavilion", "deposit", "food"]
    await update(context, tools, plan=[{"id": "thanks", "title": "Send thank-you notes"}])
    assert store.get(goal.id).plan[-1].id == "thanks"
    assert store.get(goal.id).plan[-1].status == "pending"


async def test_removed_step_drops_dependency_links(planned):
    store, goal, context, tools = planned
    await update(context, tools, plan=[{"id": "guests", "remove": True}])
    saved = store.get(goal.id).plan
    assert [step.id for step in saved] == ["book_pavilion", "food"]
    assert saved[0].depends_on == [] and saved[1].depends_on == ["book_pavilion"]


async def test_plan_change_errors_leave_the_plan_as_it_was(planned):
    store, goal, context, tools = planned
    with bind(context):
        await tools["read_goal"]()
        cases = {
            "Error: Step 'missing' does not exist.": [{"id": "missing", "remove": True}],
            "Error: Use before only when adding a step.": [{"id": "food", "before": "guests"}],
            "Error: Change each step at most once per update.": [{"id": "food", "status": "done"},
                                                                  {"id": "food", "notes": "x"}],
            "Error: Plan dependencies cannot contain cycles.": [{"id": "guests", "depends_on": ["food"]}],
        }
        for expected, plan in cases.items():
            assert await call(tools["update_goal"], plan=plan) == expected
    assert store.get(goal.id).plan == goal.plan
    assert store.get(goal.id).revision == goal.revision


async def test_summary_is_optional_and_replaced_whole(planned):
    store, goal, context, tools = planned
    await update(context, tools, summary="The pavilion costs $80 a day.")
    await update(context, tools, plan=[{"id": "guests", "status": "done"}])
    assert store.get(goal.id).summary == "The pavilion costs $80 a day."
    await update(context, tools, summary="")
    assert store.get(goal.id).summary == ""


async def test_update_goal_does_not_choose_what_happens_next(planned):
    store, goal, context, tools = planned
    with bind(context):
        await tools["read_goal"]()
        await call(tools["update_goal"], plan=[{"id": "guests", "status": "done"}], summary="All 30 replied.")
        assert "next_action" not in json.loads(await tools["read_goal"]())
    assert store.get(goal.id).next == goal.next


async def test_step_change_with_null_fields_keeps_saved_values(planned):
    # Some providers send every optional field, as null when unused.
    store, goal, context, tools = planned
    result = await update(context, tools, plan=[{
        "id": "guests", "title": None, "status": "done", "notes": None, "depends_on": None, "before": None,
    }])
    assert result == "Saved."
    saved = store.get(goal.id).plan[0]
    assert saved.status == "done"
    assert saved.title == "Collect the guest list" and saved.notes == "12 replies so far"
