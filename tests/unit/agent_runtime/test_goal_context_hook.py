"""Goal change notices: the hook tells the run when someone else changed the goal."""

import json

import pytest

from agent_core.context import GOAL_STATE_PREFIX, ConversationHistory
from agent_core.control import ExecutionControl, StopRequestedError
from agent_core.events import AgentEvent, CompactionPayload, UserMessagePayload, publish_event
from agent_core.turn import ExecutionContext
from agent_runtime._goals import GoalContextHook
from goals import GoalRevisionTracker, GoalStore

from tests.unit.goals.support import bind, chat_turn, completed, create, goal_tools, with_plan


@pytest.fixture
def run(tmp_path):
    store = GoalStore(tmp_path / "goals")
    goal = with_plan(store, create(store, objective="Private objective"))
    chat_turn(store, goal, "owner")
    history = ConversationHistory(system_message="Base", conversation_id="chat")
    context = ExecutionContext(execution_id="root.agent", conversation_id="chat", run_id="run",
                               event_sink=history, control=ExecutionControl())
    tracker = GoalRevisionTracker()
    hook = GoalContextHook(store, goal.id, "owner", enabled=lambda: True, wakeup=False, tracker=tracker)
    tools = goal_tools(store, goal, "owner", tracker=tracker)
    return store, goal, history, context, hook, tools, tracker


def notices(history):
    return [event["data"]["reason"] for event in history.recorded_events
            if event["type"] == "goal" and event["data"]["kind"] == "state_notice"]


async def test_chat_turn_starts_with_one_notice_that_names_no_tool_or_revision(run):
    store, goal, history, context, hook, _tools, _tracker = run
    with bind(context):
        publish_event(AgentEvent(payload=UserMessagePayload(type="user_message", content="How is it going?")))
        await hook.before_model(history, 1, "Agent")
        await hook.before_model(history, 2, "Agent")
    assert notices(history) == ["run_started"]
    notice = history.messages[-1]["content"]
    assert notice.startswith(GOAL_STATE_PREFIX)
    assert "read_goal" not in notice and "revision" not in notice.lower()
    assert "Private objective" not in json.dumps(history.messages)


async def test_wake_run_gets_no_start_notice(run):
    store, goal, history, context, _hook, _tools, tracker = run
    hook = GoalContextHook(store, goal.id, "owner", enabled=lambda: True, wakeup=True, tracker=tracker)
    with bind(context):
        await hook.before_model(history, 1, "Agent")
    assert notices(history) == []


async def test_own_writes_never_cause_a_notice(run):
    _store, _goal, history, context, hook, tools, _tracker = run
    with bind(context):
        await hook.before_model(history, 1, "Agent")
        await tools["read_goal"]()
        await tools["update_goal"](summary="Use referrals")
        await hook.before_model(history, 2, "Agent")
        await tools["choose_next_action"](action="continue", note="Kept going.")
        await hook.before_model(history, 3, "Agent")
    assert notices(history) == ["run_started"]


async def test_change_by_someone_else_gives_one_notice(run):
    store, goal, history, context, hook, tools, _tracker = run
    with bind(context):
        await hook.before_model(history, 1, "Agent")
        await tools["read_goal"]()
        store.update(goal.id, store.get(goal.id).revision, objective="Edited objective")
        await hook.before_model(history, 2, "Agent")
        await hook.before_model(history, 3, "Agent")
        assert notices(history) == ["run_started", "state_changed"]
        assert "Edited objective" not in json.dumps(history.messages)
        # A write is still refused until the agent reads the goal again.
        refused = await tools["update_goal"](summary="Stale")
        assert refused.startswith("Error: The goal changed since you last read it.")
        await tools["read_goal"]()
        assert await tools["update_goal"](summary="Fresh") == "Saved."
        await hook.before_model(history, 4, "Agent")
    assert notices(history) == ["run_started", "state_changed"]


async def test_compaction_clears_the_tracker_and_gives_a_notice(run):
    _store, _goal, history, context, hook, tools, tracker = run
    with bind(context):
        await hook.before_model(history, 1, "Agent")
        await tools["read_goal"]()
        first = history.recorded_events[0]["id"]
        publish_event(AgentEvent(payload=CompactionPayload(
            type="compaction", kept_from_id=first, kept_to_id=history.recorded_events[-1]["id"],
            summary_text="Earlier work.",
        )))
        await hook.before_model(history, 2, "Agent")
        assert tracker.seen is None
        assert notices(history)[-1] == "compacted"
        refused = await tools["update_goal"](summary="After compaction")
        assert refused == "Error: Read the goal with read_goal before changing it."


async def test_notices_survive_reloading_the_conversation(run):
    store, goal, history, context, hook, tools, _tracker = run
    with bind(context):
        publish_event(AgentEvent(payload=UserMessagePayload(type="user_message", content="Continue")))
        await hook.before_model(history, 1, "Agent")
        await tools["read_goal"]()
        store.update(goal.id, store.get(goal.id).revision, objective="Edited objective")
        await hook.before_model(history, 2, "Agent")
    restored = ConversationHistory(system_message="Base", conversation_id="chat")
    restored.seed_events(history.recorded_events)
    assert restored.messages == history.messages
    assert [event["content"] for event in history.recorded_events if event["type"] == "user_message"] == ["Continue"]


async def test_lost_claim_stops_the_run(run):
    store, goal, history, context, hook, _tools, _tracker = run
    with bind(context):
        await hook.before_model(history, 1, "Agent")
        store.pause(goal.id)
        with pytest.raises(StopRequestedError):
            await hook.before_model(history, 2, "Agent")


async def test_turning_goals_off_stops_the_run(run):
    store, goal, history, context, _hook, _tools, tracker = run
    hook = GoalContextHook(store, goal.id, "owner", enabled=lambda: False, wakeup=False, tracker=tracker)
    with bind(context), pytest.raises(StopRequestedError):
        await hook.before_model(history, 1, "Agent")


async def test_hook_for_a_read_only_turn_adds_no_notice(tmp_path):
    store = GoalStore(tmp_path / "goals")
    goal = completed(store, create(store))
    history = ConversationHistory(conversation_id="chat")
    hook = GoalContextHook(store, goal.id, None, enabled=lambda: True, wakeup=False, tracker=GoalRevisionTracker())
    await hook.before_model(history, 1, "Agent")
    assert notices(history) == []
