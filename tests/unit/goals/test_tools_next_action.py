"""choose_next_action: the four actions, the required note, and times."""

import json
import time

import pytest

from goals import GoalStore

from tests.unit.goals.support import bind, call, claim_wake, create, future, goal_tools, past, root_context, with_plan


@pytest.fixture
def owned(tmp_path):
    store = GoalStore(tmp_path / "goals")
    goal = with_plan(store, create(store))
    claim_wake(store, goal)
    return store, goal, root_context(), goal_tools(store, goal)


@pytest.fixture
def chicago(monkeypatch):
    monkeypatch.setenv("TZ", "America/Chicago")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


async def choose(context, tools, **arguments):
    with bind(context):
        await tools["read_goal"]()
        return await call(tools["choose_next_action"], **arguments)


async def test_each_action_returns_only_the_next_action(owned):
    store, goal, context, tools = owned
    assert json.loads(await choose(context, tools, action="continue", note="More to do.")) == {"action": "continue"}
    scheduled = json.loads(await choose(context, tools, action="schedule", note="Wait for the reply.", at=future()))
    assert set(scheduled) == {"action", "at"} and scheduled["action"] == "schedule"
    with bind(context):
        await call(tools["update_goal_questions"], changes=[{"id": "day", "question": "Which Saturday?"}])
    waiting = json.loads(await choose(context, tools, action="wait_for_input", note="Need a day.", question_ids=["day"]))
    assert waiting == {"action": "wait_for_input", "question_ids": ["day"]}
    done = json.loads(await choose(context, tools, action="complete", note="Booked it.", outcome="Booked June 14."))
    assert done == {"action": "complete", "outcome": "Booked June 14."}
    saved = store.get(goal.id)
    assert saved.ended and saved.note == "Booked it."


async def test_choose_next_action_result_has_no_revision(owned):
    _store, _goal, context, tools = owned
    result = await choose(context, tools, action="continue", note="More to do.")
    assert "revision" not in result and "claim" not in result and "wake" not in result


async def test_choose_next_action_requires_note(owned):
    store, goal, context, tools = owned
    with pytest.raises(ValueError, match="note"):
        await choose(context, tools, action="continue")
    for blank in ("", "   "):
        with pytest.raises(ValueError):
            await choose(context, tools, action="continue", note=blank)
    with pytest.raises(ValueError):
        await choose(context, tools, action="continue", note="x" * 501)
    assert store.get(goal.id).revision == goal.revision


@pytest.mark.parametrize("arguments", [
    {"action": "schedule"},
    {"action": "wait_for_input"},
    {"action": "wait_for_input", "question_ids": []},
    {"action": "complete"},
    {"action": "continue", "at": "2099-01-01T09:00:00Z"},
    {"action": "complete", "outcome": "Done", "question_ids": ["q"]},
])
async def test_choose_next_action_rejects_missing_or_unrelated_fields(owned, arguments):
    store, goal, context, tools = owned
    with pytest.raises(ValueError):
        await choose(context, tools, note="Did some work.", **arguments)
    assert store.get(goal.id).revision == goal.revision


async def test_continue_without_open_step_is_refused(owned):
    store, goal, context, tools = owned
    with bind(context):
        await tools["read_goal"]()
        await call(tools["update_goal"], plan=[{"id": "book", "status": "done"}])
        expected = "Error: Mark the step the next run should work on as in progress, or add one."
        assert await call(tools["choose_next_action"], action="continue", note="Done for now.") == expected
        result = await call(tools["choose_next_action"], action="schedule", note="Later.", at=future())
        assert result == expected
    assert store.get(goal.id).next == goal.next


async def test_past_schedule_error_includes_now(owned, chicago):
    store, goal, context, tools = owned
    result = await choose(context, tools, action="schedule", note="Later.", at=past())
    assert result.startswith("Error: The time must be in the future. It is now ")
    assert "CST" in result or "CDT" in result
    assert result.endswith("Use continue to run again right away.")
    assert store.get(goal.id).next == goal.next


async def test_saved_time_is_shown_in_local_zone(owned, chicago):
    store, goal, context, tools = owned
    result = json.loads(await choose(context, tools, action="schedule", note="Check Friday.",
                                     at="2099-11-14T00:00:00+09:00"))
    assert result == {"action": "schedule", "at": "Fri Nov 13, 9:00 AM CST"}
    assert store.get(goal.id).next.at == "2099-11-13T15:00:00+00:00"
    with bind(context):
        view = json.loads(await tools["read_goal"]())
    assert view["next_action"] == result
    assert view["now"].endswith("CST)") or view["now"].endswith("CDT)")


async def test_schedule_without_timezone_is_refused(owned):
    store, goal, context, tools = owned
    result = await choose(context, tools, action="schedule", note="Later.", at="2099-01-01T09:00:00")
    assert result == "Error: Timestamp must include a timezone offset."
    assert store.get(goal.id).next == goal.next
