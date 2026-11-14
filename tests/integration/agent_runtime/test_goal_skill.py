"""Internal goal skills are granted per owning run, never retained by the chat."""

import pytest

from agent_core.agent_capabilities import get_active_agent_capabilities
from conversations import load_loaded_skills
from goals import GoalStep, GoalStore
from skills._policy import SESSION_GOAL_SKILL_ID

from ._support import call, reply


GOAL_TOOLS = {"read_goal", "read_goal_history", "update_goal", "update_goal_questions", "choose_next_action"}


@pytest.mark.parametrize("disposition", ["paused", "cancelled", "completed"])
async def test_goal_skill_lifetime_follows_goal_ownership(harness, tmp_path, disposition):
    h = harness
    h.profile(allow_load_skills=True)
    h.skill("notes")
    store = GoalStore(tmp_path / "goals")
    h.manager._goal_store = store
    h.manager._runner.goal_store = store
    goal = store.create("goal-skill", "Arrange a neighborhood cleanup", "leaf")
    store.update(goal.id, goal.revision, plan=[GoalStep(id="reply", title="Check the park office reply",
                                                        status="in_progress")])

    async def inspect_owned(request):
        state = get_active_agent_capabilities()
        assert SESSION_GOAL_SKILL_ID in state.skill_ids
        assert SESSION_GOAL_SKILL_ID not in state.loaded_skill_ids
        assert GOAL_TOOLS <= set(request["tools"])
        assert "### Session goal" in request["messages"][0]["content"]
        yield reply(calls=[call("load_skill", name="notes")])

    finish = (
        call("choose_next_action", action="complete", note="Confirmed with the park office.",
             outcome="Cleanup arranged and confirmed")
        if disposition == "completed" else
        call("choose_next_action", action="schedule", at="2099-01-01T09:00:00+00:00", note="Waiting for a reply.")
    )
    h.provider.plan("leaf", inspect_owned, reply(calls=[call("read_goal")]), reply(calls=[finish]), reply("Saved"))
    await h.run(conversation="goal-skill")
    assert load_loaded_skills("goal-skill") == {"notes"}

    if disposition == "paused":
        store.pause(goal.id)
    elif disposition == "cancelled":
        store.cancel(goal.id)
    saved = store.get(goal.id)
    assert saved.paused if disposition == "paused" else saved.ended

    async def inspect_later_turn(request):
        state = get_active_agent_capabilities()
        assert SESSION_GOAL_SKILL_ID in state.skill_ids
        assert SESSION_GOAL_SKILL_ID not in state.loaded_skill_ids
        assert "notes" in state.skill_ids
        tools = set(request["tools"]) & GOAL_TOOLS
        if disposition == "paused":
            # A chat turn on a paused goal is a normal turn with every goal tool.
            assert tools == GOAL_TOOLS
        else:
            # An ended goal can only be read.
            assert tools == {"read_goal", "read_goal_history"}
            assert "This chat's goal has ended." in request["messages"][0]["content"]
        yield reply(calls=[call("load_skill", name="Session goal")])

    h.provider.plan("leaf", inspect_later_turn, reply("Ordinary chat"))
    await h.run(conversation="goal-skill", message="Let’s chat")
    assert any("Unknown skill 'Session goal'" in m.get("content", "")
               for m in h.provider.requests[-1]["messages"] if m["role"] == "tool")
    assert load_loaded_skills("goal-skill") == {"notes"}
    assert store.get(goal.id).paused == (disposition == "paused")

    if disposition == "paused":
        store.resume(goal.id)
    else:
        store.create("goal-skill", "Arrange the next cleanup", "leaf")
    h.provider.plan("leaf", inspect_owned, reply("Continuing"))
    await h.run(conversation="goal-skill", message="Continue the goal")
    assert load_loaded_skills("goal-skill") == {"notes"}
