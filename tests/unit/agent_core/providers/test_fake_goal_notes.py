"""The fake provider reads the goal after an app notice and follows the working step's directives."""

import json

from agent_core.context import APP_TEXT_PREFIX
from agent_core.providers._models import ChatResponse
from providers._fake import FakeProvider
from tests.e2e._protocol import bash, say


def notice(text: str = "A goal run started. Read the goal.") -> dict:
    return {"role": "user", "content": f"{APP_TEXT_PREFIX}\n{text}"}


def read_result(*steps: dict) -> dict:
    return {"role": "tool", "tool_name": "read_goal", "tool_call_id": "read",
            "content": json.dumps({"objective": "Plan the reunion", "plan": list(steps)})}


async def read_goal() -> str:
    """Read the goal."""
    return ""


async def reply(messages: list[dict], tools=None) -> ChatResponse:
    final = None
    async for chunk in FakeProvider().chat_stream(model="m", messages=messages, tools=tools):
        if isinstance(chunk, ChatResponse):
            final = chunk
    assert final is not None
    return final


async def test_notice_makes_the_fake_read_the_goal_first():
    final = await reply([notice()], tools=[read_goal])
    assert [call.function.name for call in final.message.tool_calls] == ["read_goal"]


async def test_working_step_title_is_the_task_after_the_read():
    messages = [
        notice(),
        {"role": "assistant", "content": None, "tool_calls": [{"id": "read"}]},
        read_result({"id": "done", "title": "Done step", "status": "done"},
                    {"id": "book", "title": say("Booked the pavilion."), "status": "in_progress"}),
    ]
    assert (await reply(messages, tools=[read_goal])).message.content == "Booked the pavilion."


async def test_first_pending_step_is_used_when_none_is_in_progress():
    messages = [notice(), read_result({"id": "book", "title": say("Pending step.")})]
    assert (await reply(messages, tools=[read_goal])).message.content == "Pending step."


async def test_steps_count_from_the_read_not_the_notice():
    messages = [
        notice(),
        read_result({"id": "run", "title": bash("echo one") + say("All done."), "status": "in_progress"}),
        {"role": "assistant", "content": None, "tool_calls": [{"id": "x"}]},
        {"role": "tool", "tool_name": "run_bash_cmd", "tool_call_id": "x", "content": "one"},
    ]
    final = await reply(messages, tools=[read_goal])
    assert final.message.tool_calls is None
    assert final.message.content == "All done."


async def test_typed_message_after_a_notice_is_the_task():
    messages = [notice("The user edited the goal."), {"role": "user", "content": say("Here is the plan.")}]
    assert (await reply(messages, tools=[read_goal])).message.content == "Here is the plan."
