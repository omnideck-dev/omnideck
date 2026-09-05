"""Profile, history, delegation, and event contracts across real execution paths."""

import base64
import json

import pytest

from agent_runtime import RunAttachment
from agents._agent_profiles import save_agent_profile
from artifacts import list_artifacts
from conversations import (
    get_or_create_conversation, load_browser_tabs, load_events_jsonl,
    load_loaded_skills, load_terminal,
)
from sdk.events import AgentEvent, BrowserScreenshotPayload, FileOutputPayload, TerminalOutputPayload, publish_event
from sdk.providers import ProviderError
from tasks import TaskExecutor

from ._support import assert_lifecycle, call, payloads, reply


async def invoke(h, mode):
    if mode == "routine":
        routine = h.store.create_routine("routine purpose", auto_run=False)
        task = h.store.create_task(routine.id, "task", "leaf input", agent_profile="leaf")
        run = h.store.queue_run(routine.id)
        result = h.store.get_task_results(run.id)[0]
        output, files = await TaskExecutor(h.store).run(result, task)
        conversation = h.store.get_task_results(run.id)[0].conversation_id
        return load_events_jsonl(conversation), output
    if mode == "child":
        h.profile("parent", allow_spawn=True, temperature=0.9)
        h.provider.plan("parent",
            reply(calls=[call("spawn_agent", instructions="leaf input", profile="leaf", agent_name="LEAF")]),
            reply("parent done"),
        )
        events = await h.run("parent", message="private parent request")
    else:
        events = await h.run(message="leaf input")
    return [e.to_flat_dict("contract") for e in events], "parent done" if mode == "child" else "leaf done"


@pytest.mark.parametrize("mode", ["root", "child", "routine"])
async def test_profile_configuration_reaches_provider_through_every_entry(harness, mode):
    async def leaf_tool(value: str) -> str:
        return f"leaf-result:{value}"

    h = harness
    h.skill("leaf-skill", leaf_tool)
    h.profile(
        skills=["leaf-skill"], temperature=0.23, top_p=0.7, think=True,
        browser_profile_id="empty", context_window=120_000,
    )
    h.provider.plan("leaf",
        reply(calls=[call("leaf_tool", value="proof")]), reply("leaf done"),
    )
    events, output = await invoke(h, mode)

    requests = [r for r in h.provider.requests if r["model"] == "leaf"]
    assert len(requests) == 2
    first, second = requests
    assert first["options"]["temperature"] == 0.23
    assert first["options"]["top_p"] == 0.7
    assert first["options"]["num_ctx"] == 120_000
    assert first["think"] is True
    assert "system:leaf" in first["messages"][0]["content"]
    assert "guidance:leaf-skill" in first["messages"][0]["content"]
    assert "leaf_tool" in first["tools"]
    assert "spawn_agent" not in first["tools"]
    assert "load_skill" not in first["tools"]
    assert any(m.get("content") == "leaf-result:proof" for m in second["messages"])
    assert "private parent request" not in json.dumps(first["messages"])
    preparation = [r for r in h.browser_calls if r["agent_profile_id"] == "leaf"]
    assert len(preparation) == 1
    assert preparation[0]["browser_profile_id"] == "empty"
    assert preparation[0]["agent_id"] == first["agent_id"]
    assert first["agent_id"] in h.exited_agents
    completed = [e for e in events if e["type"] == "agent_completed"]
    assert all(e["status"] == "success" for e in completed)
    if mode == "routine":
        assert h.exited_conversations == [first["conversation_id"]]
        assert output == "leaf done"


async def test_attachment_and_prior_turn_survive_disk_rehydration(harness, monkeypatch):
    h = harness
    h.profile()
    h.provider.plan("leaf", reply("first answer"), reply("second answer"))
    first = await h.run(message="inspect attachment", attachments=[
        RunAttachment(base64_encoded=base64.b64encode(b"file proof").decode(),
                      content_type="text/plain", filename="proof.txt"),
    ])
    sent = payloads(first, "user_message")[0]
    path = sent.attachments[0].path
    assert sent.content == "inspect attachment"
    assert (h.home / "uploads/proof.txt").read_text() == "file proof"
    assert path in h.provider.requests[0]["messages"][1]["content"]

    # Force the next turn through real JSONL hydration, not the warm object.
    from collections import OrderedDict
    monkeypatch.setattr("conversations._cache._conversations", OrderedDict())
    second = await h.run(message="continue")
    messages = h.provider.requests[-1]["messages"]
    assert [m["content"] for m in messages if m["role"] == "assistant"] == ["first answer"]
    assert [m["content"] for m in messages if m["role"] == "user"][-1] == "continue"
    assert path in messages[1]["content"]
    persisted = load_events_jsonl("contract")
    assert len({e["id"] for e in persisted}) == len(persisted)
    assert_lifecycle(first, {"LEAF": "success"})
    assert_lifecycle(second, {"LEAF": "success"})


async def test_loaded_skills_survive_turns_while_profile_baseline_can_change(harness):
    h = harness

    async def extra_tool() -> str:
        return "extra"

    h.skill("original")
    h.skill("replacement")
    h.skill("extra", extra_tool)
    profile = h.profile(skills=["original"], allow_load_skills=True)
    h.provider.plan("leaf",
        reply(calls=[call("load_skill", name="extra")]),
        reply("learned"),
        reply("continued"),
    )
    await h.run()
    assert "extra_tool" not in h.provider.requests[0]["tools"]
    assert "extra_tool" in h.provider.requests[1]["tools"]
    assert set(load_loaded_skills("contract")) == {"extra"}
    save_agent_profile(profile.model_copy(update={"skills": ["replacement"]}))
    await h.run(message="next turn")
    request = h.provider.requests[-1]
    assert "extra_tool" in request["tools"]
    assert "guidance:replacement" in request["messages"][0]["content"]
    assert "guidance:extra" in request["messages"][0]["content"]
    assert "guidance:original" not in request["messages"][0]["content"]


async def test_nested_children_have_isolated_history_and_paired_results(harness):
    h = harness
    h.profile("root", allow_spawn=True)
    h.profile("child", allow_spawn=True)
    h.profile("grandchild")
    h.provider.plan("root",
        reply(calls=[call("spawn_agent", instructions="child request", profile="child", agent_name="CHILD")]),
        reply("root answer"),
    )
    h.provider.plan("child",
        reply(calls=[call("spawn_agent", instructions="grandchild request", profile="grandchild", agent_name="GRANDCHILD")]),
        reply("child answer"),
    )
    h.provider.plan("grandchild", reply("grandchild answer"))
    events = await h.run("root", message="root secret")
    assert_lifecycle(events, {"ROOT": "success", "CHILD": "success", "GRANDCHILD": "success"})
    started = {p.agent_name: p for p in payloads(events, "agent_started")}
    assert started["CHILD"].parent_agent_id == started["ROOT"].agent_id
    assert started["GRANDCHILD"].parent_agent_id == started["CHILD"].agent_id
    spawns = payloads(events, "spawn_requested")
    assert {s.correlation_id for s in spawns} == {
        started["CHILD"].correlation_id, started["GRANDCHILD"].correlation_id,
    }
    for name, request_text in (("child", "child request"), ("grandchild", "grandchild request")):
        request = next(r for r in h.provider.requests if r["model"] == name)
        assert [m["content"] for m in request["messages"] if m["role"] == "user"] == [request_text]
        assert "root secret" not in json.dumps(request["messages"])
    root_last = [r for r in h.provider.requests if r["model"] == "root"][-1]
    assert "child answer" in json.dumps(root_last["messages"])
    assert "grandchild answer" not in json.dumps(root_last["messages"])
    calls = [tc.id for p in payloads(events, "iteration") for tc in p.tool_calls]
    results = payloads(events, "tool_result")
    assert all(calls) and sorted(calls) == sorted(r.tool_call_id for r in results)
    persisted = load_events_jsonl("contract")
    assert len(persisted) == len({e["id"] for e in persisted})
    assert set(h.exited_agents) == {p.agent_id for p in started.values()}


async def test_child_loading_skill_does_not_grant_parent_its_tools(harness):
    h = harness

    async def child_only() -> str:
        return "child secret"

    h.skill("child-only", child_only)
    h.profile("root", allow_spawn=True)
    h.profile("child", allow_load_skills=True)
    h.provider.plan("root",
        reply(calls=[call("spawn_agent", instructions="child work", profile="child", agent_name="CHILD")]),
        reply("parent done"),
    )
    h.provider.plan("child",
        reply(calls=[call("load_skill", name="child-only")]),
        reply(calls=[call("child_only")]),
        reply("child summary"),
    )
    events = await h.run("root")
    assert_lifecycle(events, {"ROOT": "success", "CHILD": "success"})
    root_requests = [r for r in h.provider.requests if r["model"] == "root"]
    assert all("child_only" not in r["tools"] for r in root_requests)
    assert all("guidance:child-only" not in r["messages"][0]["content"] for r in root_requests)
    assert "child secret" not in json.dumps(root_requests[-1]["messages"])
    assert load_loaded_skills("contract") == set()


@pytest.mark.parametrize("source", ["root", "child"])
async def test_output_events_reach_transcript_artifact_and_workspace_writers(harness, source):
    h = harness
    output_path = h.home / "result.txt"
    output_path.write_text("proof")

    async def emit_outputs() -> str:
        for payload in (
            FileOutputPayload(type="file_output", filename="result.txt", content_type="text/plain", path=str(output_path)),
            BrowserScreenshotPayload(type="browser_screenshot", tab_id=7, open_tab_ids=[7],
                                     url="about:blank", title="Proof", screenshot="cHJvb2Y="),
            TerminalOutputPayload(type="terminal_output", cmd_id="command-proof", cmd="echo proof",
                                  status="completed", stdout="proof", exit_code=0),
        ):
            publish_event(AgentEvent(payload=payload))
        return "outputs saved"

    h.skill("output", emit_outputs)
    h.profile(skills=["output"])
    h.provider.plan("leaf", reply(calls=[call("emit_outputs")]), reply("leaf done"))
    events, _output = await invoke(h, source)
    emitted = next(e for e in events if e["type"] == "file_output")
    indexed = list_artifacts("contract")
    assert [(a.path, a.agent_name) for a in indexed] == [(str(output_path), "LEAF")]
    assert load_browser_tabs("contract")[0]["agent_id"] == emitted["agent_id"]
    assert load_terminal("contract")[emitted["agent_id"]][0]["stdout"] == "proof"
    persisted = load_events_jsonl("contract")
    assert len([e for e in persisted if e["type"] == "file_output"]) == 1
    assert not any(e["type"] in ("browser_screenshot", "terminal_output") for e in persisted)


async def test_child_provider_failure_is_visible_and_parent_can_recover(harness):
    h = harness
    h.profile("root", allow_spawn=True)
    h.profile("child")
    h.provider.plan("root",
        reply(calls=[call("spawn_agent", instructions="child work", profile="child", agent_name="CHILD")]),
        reply("recovered"),
    )
    h.provider.plan("child", ProviderError("child unavailable", retryable=False))
    events = await h.run("root")
    assert_lifecycle(events, {"ROOT": "success", "CHILD": "error"})
    errors = [e for e in events if e.payload.type == "error"]
    child_id = next(p.agent_id for p in payloads(events, "agent_started") if p.agent_name == "CHILD")
    assert len(errors) == 1 and errors[0].agent_id == child_id
    root_request = [r for r in h.provider.requests if r["model"] == "root"][-1]
    assert any(m["role"] == "tool" and "child unavailable" in m["content"] for m in root_request["messages"])
