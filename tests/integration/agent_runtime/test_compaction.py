"""Keep compaction connected to the real hooks, history views, and disk log."""

import json

import pytest

from conversations import load_events_jsonl

from ._support import assert_lifecycle, call, reply


@pytest.mark.parametrize("child", [False, True], ids=["root", "child"])
async def test_compaction_preserves_tool_pairs_and_agent_scope(harness, monkeypatch, child):
    h = harness

    async def unload(_model):
        pass  # External Ollama process boundary only.

    async def lookup(value: str) -> str:
        return f"finding:{value}"

    monkeypatch.setattr("sdk.context._strategy._unload_model", unload)
    h.skill("lookup", lookup)
    h.profile(skills=["lookup"], context_window=1000, compaction_threshold=0.01)
    h.provider.plan("leaf", *[
        reply(f"step {i}", calls=[call("lookup", value=str(i))]) for i in range(5)
    ], reply("leaf complete"))
    h.provider.plan("summary", *[reply("earlier findings summary") for _ in range(10)])
    if child:
        h.profile("root", allow_spawn=True)
        h.provider.plan("root", reply(calls=[
            call("spawn_agent", profile="leaf", agent_name="LEAF", instructions="leaf task"),
        ]), reply("root complete"))
    events = await h.run("root" if child else "leaf", message="root private task" if child else "leaf task")
    assert_lifecycle(events, {"ROOT": "success", "LEAF": "success"} if child else {"LEAF": "success"})
    compacted = [e for e in events if e.payload.type == "compaction"]
    assert compacted
    leaf_id = next(r["agent_id"] for r in h.provider.requests if r["model"] == "leaf")
    assert {e.agent_id for e in compacted} == {leaf_id}
    summaries = [r for r in h.provider.requests if r["model"] == "summary"]
    assert len(summaries) == len(compacted)
    assert all("root private task" not in json.dumps(r["messages"]) for r in summaries)
    leaf_last = next(r for r in reversed(h.provider.requests) if r["model"] == "leaf")
    assert "earlier findings summary" in json.dumps(leaf_last["messages"])
    assert "finding:4" in json.dumps(leaf_last["messages"])
    pending = set()
    for message in leaf_last["messages"]:
        for tc in message.get("tool_calls", []) or []:
            pending.add(tc["id"])
        if message["role"] == "tool":
            assert message["tool_call_id"] in pending
            pending.remove(message["tool_call_id"])
    assert not pending
    persisted = load_events_jsonl("contract")
    assert {e["id"] for e in persisted if e["type"] == "compaction"} == {e.id for e in compacted}
    if child:
        root_last = next(r for r in reversed(h.provider.requests) if r["model"] == "root")
        assert "earlier findings summary" not in json.dumps(root_last["messages"])
        assert "leaf complete" in json.dumps(root_last["messages"])
