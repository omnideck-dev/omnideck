"""The fake provider skips goal state notices but treats a goal wakeup as the newest task."""

from agent_core.context._view import build_llm_view
from agent_core.providers._models import ChatResponse
from providers._fake import FakeProvider
from tests.e2e._protocol import bash, say
from tests.unit.agent_core.context._event_builders import CONV, ROOT, _iter, _started, _user


def goal_event(data: dict, evt_id: str) -> dict:
    return {
        "id": evt_id, "type": "goal", "timestamp": "2026-01-01T00:00:30", "conversation_id": CONV,
        "agent_id": ROOT, "depth": 0, "goal_id": "goal_1", "data": data,
    }


def notice(evt_id: str = "evt_notice") -> dict:
    return goal_event({"kind": "state_notice", "revision": 3, "reason": "state_changed"}, evt_id)


def wakeup(step: str, evt_id: str = "evt_wake") -> dict:
    return goal_event({"kind": "wakeup", "wake_id": "wake_1", "reason": "planned", "step": step}, evt_id)


async def reply(messages: list[dict]) -> ChatResponse:
    final = None
    async for chunk in FakeProvider().chat_stream(model="m", messages=messages, tools=None):
        if isinstance(chunk, ChatResponse):
            final = chunk
    assert final is not None
    return final


async def test_state_notice_is_not_treated_as_the_last_user_message():
    messages = build_llm_view([_started(ROOT, "Agent"), _user(ROOT, say("Here is the plan.")), notice()])
    assert messages[-1]["content"].startswith("[System activity: goal state]")
    assert (await reply(messages)).message.content == "Here is the plan."


async def test_state_notice_does_not_restart_a_running_script():
    messages = [
        {"role": "user", "content": bash("echo one") + say("All done.")},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "x"}]},
        {"role": "tool", "tool_name": "run_bash_cmd", "tool_call_id": "x", "content": "one"},
        build_llm_view([_started(ROOT, "Agent"), _user(ROOT, "x"), notice()])[-1],
    ]
    final = await reply(messages)
    assert final.message.tool_calls is None
    assert final.message.content == "All done."


async def test_goal_wakeup_is_the_newest_task():
    events = [
        _started(ROOT, "Agent"), _user(ROOT, say("Started the plan.")), _iter(ROOT, 0, content="Started the plan."),
        wakeup(say("Woke up for the next step.")),
    ]
    messages = build_llm_view(events)
    assert messages[-1]["content"].startswith("[System activity: goal wakeup]")
    assert (await reply(messages)).message.content == "Woke up for the next step."
