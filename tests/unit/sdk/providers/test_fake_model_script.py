"""Protocol guarantees needed to drive runtime E2E without event fixtures."""

import pytest

from sdk.providers import ChatResponse
from sdk.providers._fake import FakeProvider
from tests.e2e._protocol import model_script, model_tool, say, spawn


def tool():
    return "result"


async def response(messages):
    chunks = [c async for c in FakeProvider().chat_stream(model="fake", messages=messages, tools=[tool])]
    assert isinstance(chunks[-1], ChatResponse)
    return chunks[-1], chunks[:-1]


async def test_script_streams_thinking_and_content_before_real_tool_request():
    prompt = model_script(
        {"thinking": "plan", "content": "starting", "tool_calls": [model_tool("tool")]},
        {"content": "finished"},
    )
    messages = [{"role": "user", "content": prompt}]
    first, deltas = await response(messages)
    assert [d.thinking for d in deltas if d.thinking] == ["plan"]
    assert [d.content for d in deltas if d.content] == ["starting"]
    call = first.message.tool_calls[0]
    assert call.function.name == "tool"
    repeated, _ = await response(messages)
    assert repeated == first  # A retry cannot consume a mutable fake cursor.
    messages += [{"role": "assistant", "tool_calls": [call.model_dump()]},
                 {"role": "tool", "tool_call_id": call.id, "content": "real result"}]
    final, _ = await response(messages)
    assert final.message.content == "finished" and not final.message.tool_calls


async def test_compacted_history_keeps_script_progress_and_new_turn_restarts():
    prompt = model_script(*[
        {"content": str(i), "tool_calls": [model_tool("tool", value=i)]} for i in range(4)
    ], {"content": "done"})
    user = {"role": "user", "content": prompt}
    messages = [user]
    for i in range(4):
        step, _ = await response(messages)
        assert step.message.content == str(i)
        call = step.message.tool_calls[0]
        # Simulate the provider-visible compacted view: only recent work remains.
        messages = [user, {"role": "assistant", "content": "earlier summary"},
                    {"role": "tool", "tool_call_id": call.id, "content": "result"}]
    final, _ = await response(messages)
    assert final.message.content == "done"
    restarted, _ = await response(messages + [user])
    assert restarted.message.content == "0"


async def test_nested_script_is_not_consumed_by_parent_protocol():
    child = model_script({"content": "child answer with <<END>> text"})
    messages = [{"role": "user", "content": spawn(child, profile="child") + say("parent answer")}]
    first, _ = await response(messages)
    call = first.message.tool_calls[0]
    assert call.function.name == "spawn_agent"
    assert call.function.arguments["instructions"] == child
    child_response, _ = await response([{"role": "user", "content": child}])
    assert child_response.message.content == "child answer with <<END>> text"


async def test_skill_setup_does_not_advance_script():
    prompt = model_script(
        {"content": "writing", "tool_calls": [model_tool("write_file", path="p", content="c")]},
        {"content": "done"},
    )
    messages = [{"role": "user", "content": prompt}]
    setup, _ = await response(messages)
    assert setup.message.tool_calls[0].function.name == "load_skill"
    messages += [{"role": "tool", "tool_call_id": setup.message.tool_calls[0].id, "content": "loaded"}]
    def write_file():
        pass
    actual = await FakeProvider().chat(model="fake", messages=messages, tools=[write_file])
    assert actual.message.content == "writing"
    assert actual.message.tool_calls[0].function.name == "write_file"


async def test_nonfinal_response_without_tools_is_rejected():
    with pytest.raises(ValueError, match="non-final"):
        await response([{"role": "user", "content": model_script({"content": "early end"}, {"content": "unreachable"})}])
