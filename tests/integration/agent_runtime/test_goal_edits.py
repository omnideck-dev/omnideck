"""A user's goal edit reaches the model at the start of the next run."""

from agent_core.context import APP_TEXT_PREFIX
from agent_runtime import AgentRunRequest

from ._support import reply


async def test_edited_message_comes_before_the_typed_message_in_the_model_request(harness):
    h = harness
    h.profile()
    store = h.goals
    goal = h.goal("edited-goal", "Plan a cleanup", "leaf")
    h.provider.plan("leaf", reply("Hello"), reply("Noted the change"))
    first = await h.manager.start(AgentRunRequest("edited-goal", "Hello", None, "leaf"))
    assert (await first.wait()).status == "success"
    goal = store.get(goal.id)
    store.update(goal.id, goal.revision, objective="Plan a beach cleanup", actor="user")
    second = await h.manager.start(AgentRunRequest("edited-goal", "Keep going", None, "leaf"))
    assert (await second.wait()).status == "success"
    users = [m["content"] for m in h.provider.requests[-1]["messages"] if m["role"] == "user"]
    edited = next(index for index, content in enumerate(users) if content.startswith(APP_TEXT_PREFIX)
                  and "The user edited the goal" in content)
    assert users[edited + 1:] == ["Keep going"]
