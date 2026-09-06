"""Drive real runtime ownership and agent core scopes through an HTTP channel."""

import asyncio
import json

import pytest
from aiohttp import web

from conversations import load_events_jsonl
from agent_core.events import get_current_agent_id
from agent_core.providers import ChatDelta, ProviderError
from agent_core.turn import get_conversation_id
from server._agent_run_routes import register_agent_run_routes
from server._agent_runtime import AGENT_RUNTIME_KEY

from ._support import assert_lifecycle, call, collect, payloads, reply


@pytest.mark.parametrize("outcome", ["success", "stopped", "error"])
async def test_http_disconnect_replay_control_and_next_turn(harness, aiohttp_client, outcome):
    h = harness
    release = asyncio.Event()

    async def checkpoint() -> str:
        return "checkpoint reached"

    async def stream(_request):
        yield ChatDelta(content="partial ")
        await release.wait()
        if outcome == "error":
            raise ProviderError("provider unavailable", retryable=False)
        yield ChatDelta(content="tail")
        yield reply("partial tail", calls=[call("checkpoint")])

    h.skill("checkpoint", checkpoint)
    h.profile(skills=["checkpoint"])
    h.provider.plan("leaf", stream)
    if outcome == "success":
        h.provider.plan("leaf", reply("finished"))
    app = web.Application()
    app[AGENT_RUNTIME_KEY] = h.manager
    register_agent_run_routes(app)
    client = await aiohttp_client(app)
    request = {"conversation_id": "contract", "profile_id": "leaf", "message": "work"}
    initial = await client.post("/api/chat", json=request)
    assert initial.status == 200
    prefix = []
    while True:
        record = json.loads(await asyncio.wait_for(initial.content.readline(), 5))
        prefix.append(record)
        if record["payload"]["type"] == "content":
            break
    root_id = next(r["payload"]["agent_id"] for r in prefix if r["payload"]["type"] == "agent_started")
    run_id = record["run_id"]
    cursor = record["seq"]
    initial.close()
    assert h.manager.active_for_conversation("contract").run_id == run_id
    conflict = await client.post("/api/chat", json=request)
    assert conflict.status == 409
    invalid = await client.get(f"/api/chat/runs/{run_id}/events?after=999999")
    assert invalid.status == 400

    resumed = await client.get(f"/api/chat/runs/{run_id}/events?after={cursor}")
    assert resumed.status == 200
    if outcome == "stopped":
        response = await client.post("/api/chat/stop?conversation_id=contract")
        assert response.status == 200
    elif outcome == "success":
        response = await client.post("/api/nudge", json={
            "conversation_id": "contract", "agent_id": root_id, "message": "new priority",
        })
        assert response.status == 200
    release.set()
    tail = [json.loads(line) for line in (await asyncio.wait_for(resumed.text(), 5)).splitlines()]
    records = prefix + tail
    assert [r["seq"] for r in records] == list(range(1, len(records) + 1))
    assert {r["run_id"] for r in records} == {run_id}
    assert len({r["id"] for r in records}) == len(records)
    types = [r["payload"]["type"] for r in records]
    assert types.count("agent_started") == types.count("agent_completed") == types.count("turn_end") == 1
    assert types[-1] == "turn_end"
    completed = next(r["payload"] for r in records if r["payload"]["type"] == "agent_completed")
    assert completed["status"] == outcome
    persisted = load_events_jsonl("contract")
    expected_partial = "partial " if outcome == "error" else "partial tail"
    assert [r["content"] for r in persisted if r["type"] == "iteration"][0] == expected_partial
    assert types.count("error") == (1 if outcome == "error" else 0)
    if outcome == "success":
        assert "new priority" in json.dumps(h.provider.requests[-1]["messages"])
        assert len([e for e in persisted if e["type"] == "user_message" and e.get("is_nudge")]) == 1
    assert get_conversation_id() is None
    assert get_current_agent_id() is None
    assert h.manager.active_for_conversation("contract") is None
    assert (await client.get(f"/api/chat/runs/{run_id}/events")).status == 404

    # The same conversation must be usable after every terminal outcome. This
    # also detects leaked stop signals, observers, or duplicate persistence.
    h.provider.plan("leaf", reply("fresh turn"))
    later = await h.run(message="continue")
    assert_lifecycle(later, {"LEAF": "success"})
    all_persisted = load_events_jsonl("contract")
    assert len({e["id"] for e in all_persisted}) == len(all_persisted)
    assert len([e for e in all_persisted if e["type"] == "agent_completed"]) == 2


async def test_parallel_children_overlap_without_crossing_state_or_results(harness):
    h = harness
    h.config.parallel.enabled = True
    h.profile("root", allow_spawn=True)
    entered = {name: asyncio.Event() for name in ("left", "right")}
    release = {name: asyncio.Event() for name in entered}
    right_finished = asyncio.Event()

    def child_stream(name):
        async def stream(_request):
            entered[name].set()
            await release[name].wait()
            yield reply(f"{name} answer")
        return stream

    for name in entered:
        h.skill(name)
        h.profile(name, skills=[name])
        h.provider.plan(name, child_stream(name))
    h.provider.plan("root", reply(calls=[
        call("spawn_agent", profile=name, agent_name=name.upper(), instructions=f"{name} private request")
        for name in entered
    ]), reply("merged"))
    _info, stream = await h.start("root")
    drain = asyncio.create_task(collect(stream))
    async def watch_right():
        async for record in _info.events():
            p = record.event.payload
            if p.type == "agent_completed" and p.agent_name == "RIGHT":
                right_finished.set()
                return
    watcher = asyncio.create_task(watch_right())
    try:
        await asyncio.wait_for(asyncio.gather(*(e.wait() for e in entered.values())), 5)
        # Finish right first; positional pairing would silently swap results.
        release["right"].set()
        await asyncio.wait_for(right_finished.wait(), 5)
        release["left"].set()
        events = [r.event for r in await drain]
    finally:
        for event in release.values():
            event.set()
        await drain
        await watcher
    assert_lifecycle(events, {"ROOT": "success", "LEFT": "success", "RIGHT": "success"})
    children = {p.agent_name: p for p in payloads(events, "agent_started") if p.agent_name != "ROOT"}
    assert children["LEFT"].agent_id != children["RIGHT"].agent_id
    for name, other in (("left", "right"), ("right", "left")):
        request = next(r for r in h.provider.requests if r["model"] == name)
        assert request["agent_id"] == children[name.upper()].agent_id
        assert f"guidance:{name}" in request["messages"][0]["content"]
        assert f"guidance:{other}" not in json.dumps(request["messages"])
        assert f"{other} private request" not in json.dumps(request["messages"])
    spawned = {tc.id: tc.arguments["profile"]
               for p in payloads(events, "iteration") for tc in p.tool_calls}
    assert len(spawned) == 2
    for result in payloads(events, "tool_result"):
        assert result.content == f"{spawned[result.tool_call_id]} answer"
    root_final = next(r for r in reversed(h.provider.requests) if r["model"] == "root")
    assert {m["content"] for m in root_final["messages"] if m["role"] == "tool"} == {"left answer", "right answer"}
