"""Shared application execution with the real FakeProvider instruction protocol."""

import asyncio
from copy import deepcopy

import pytest

from agent_runtime import AgentRunRequest
from conversations import load_events_jsonl, load_loaded_skills, list_conversations
from providers._fake import FakeProvider
from sdk.turn._models import _current_execution
from tasks import TaskExecutor
from tools.memory import remember
from tests.e2e._protocol import call_tool, say, spawn


async def _run(runtime, request):
    handle = await runtime.start(request)
    return await handle.wait()


class ObservedFakeProvider(FakeProvider):
    """Observe ownership and model inputs without replacing provider behavior."""

    def __init__(self, runtime):
        self.runtime = runtime
        self.sessions = {}
        self.requests = []
        self.spawn_tools = {}

    async def chat_stream(self, **kwargs):
        context = _current_execution.get()
        session = self.runtime._runs_by_id[context.run_id]
        self.sessions[context.run_id] = session
        owner = session.executions[context.execution_id]
        assert owner.run_id == context.run_id
        assert owner.parent_execution_id == context.parent_execution_id
        if context.parent_execution_id:
            assert context.parent_execution_id in session.executions
        for tool in kwargs.get("tools", []):
            if tool.__name__ == "spawn_agent":
                self.spawn_tools[kwargs["model"]] = tool
        self.requests.append(
            {
                "model": kwargs["model"],
                "context": context,
                "messages": deepcopy(kwargs["messages"]),
            }
        )
        async for chunk in super().chat_stream(**kwargs):
            yield chunk


@pytest.mark.parametrize("entry", ["root", "child", "routine"])
async def test_shared_runner_preserves_delegation_ownership_and_real_tool_results(harness, monkeypatch, entry):
    h = harness
    await remember("root-memory", "interactive-memory-proof")
    h.profile("parent", allow_spawn=True)
    h.profile("child", allow_spawn=True, skills=["proof"])
    h.profile("leaf", skills=["proof"])
    tool_calls = []

    async def proof(value: str) -> str:
        """Record a concrete tool invocation."""
        tool_calls.append((_current_execution.get().execution_id, value))
        return f"proof:{value}"

    h.skill("proof", proof)
    instruction = call_tool("proof", value="leaf") + say("leaf summary")
    if entry in ("child", "routine"):
        instruction = spawn(instruction, profile="leaf", name="LEAF") + say("child summary")
    if entry == "child":
        instruction = spawn(instruction, profile="child", name="CHILD") + say("parent summary")

    if entry == "routine":
        routine = h.store.create_routine("purpose", auto_run=False)
        task = h.store.create_task(routine.id, "delegate", instruction, agent_profile="child")
        run = h.store.queue_run(routine.id)
        task_result = h.store.get_task_results(run.id)[0]
        executor = TaskExecutor(h.store, h.manager)
        runtime = h.manager
    else:
        runtime = h.manager
    provider = ObservedFakeProvider(runtime)
    monkeypatch.setattr("agent_runtime._factory.get_provider", lambda _: provider)

    if entry == "routine":
        output, _ = await executor.run(task_result, task)
        assert output == "child summary"
        conversation = h.store.get_task_results(run.id)[0].conversation_id
    else:
        conversation = "shared-runner"
        await _run(runtime, AgentRunRequest(
                conversation_id=conversation,
                profile_id="parent" if entry == "child" else "leaf",
                message=instruction,
                attachments=None,
                ))
    if entry != "routine":
        summary = next(c for c in list_conversations() if c.conversation_id == conversation)
        assert summary.turn_count == 1
        assert summary.first_message == (instruction[:200] + "..." if len(instruction) > 200 else instruction)
    events = load_events_jsonl(conversation)
    starts = [e for e in events if e["type"] == "agent_started"]
    completions = [e for e in events if e["type"] == "agent_completed"]
    assert len(starts) == {"root": 1, "child": 3, "routine": 2}[entry]
    assert {e["agent_id"] for e in starts} == {e["agent_id"] for e in completions}
    assert all(e["status"] == "success" for e in completions)
    assert len({r["context"].run_id for r in provider.requests}) == 1
    assert len(tool_calls) == 1 and tool_calls[0][1] == "leaf"
    leaf = next(r for r in provider.requests if r["model"] == "leaf")
    assert tool_calls[0][0] == leaf["context"].execution_id
    assert [m["content"] for m in leaf["messages"] if m["role"] == "user"] == [
        call_tool("proof", value="leaf") + say("leaf summary")
    ]
    assert any(e["type"] == "tool_result" and e["content"] == "proof:leaf" for e in events)
    for request in provider.requests:
        includes_memory = "interactive-memory-proof" in request["messages"][0]["content"]
        assert includes_memory == (entry != "routine" and request["context"].parent_execution_id is None)
    assert runtime._runs_by_id == {}
    assert set(h.exited_agents) == {e["agent_id"] for e in starts}
    assert load_loaded_skills(conversation) == set()
    for tool in provider.spawn_tools.values():
        with pytest.raises(RuntimeError, match="owning parent"):
            await tool(instructions=say("must not run"), profile="leaf")


async def test_spawn_tool_rejects_use_from_a_different_live_parent(harness, monkeypatch):
    h = harness
    h.profile("parent", allow_spawn=True)
    h.profile("child", skills=["ownership"], allow_spawn=True)
    h.profile("leaf")
    runtime = h.manager
    provider = ObservedFakeProvider(runtime)
    monkeypatch.setattr("agent_runtime._factory.get_provider", lambda _: provider)
    rejected = []

    async def use_parent_tool() -> str:
        """Attempt to use a different execution's tool while both are alive."""
        with pytest.raises(RuntimeError, match="owning parent"):
            await provider.spawn_tools["parent"](instructions=say("wrong owner"), profile="leaf")
        rejected.append(True)
        return "rejected"

    h.skill("ownership", use_parent_tool)
    child = (
        call_tool("use_parent_tool") + spawn(say("valid grandchild"), profile="leaf", name="LEAF") + say("child done")
    )
    await _run(runtime, AgentRunRequest(
            conversation_id="bound-owner",
            profile_id="parent",
            attachments=None,
            message=spawn(child, profile="child", name="CHILD") + say("parent done"),
        ))
    assert rejected == [True]
    starts = [e for e in load_events_jsonl("bound-owner") if e["type"] == "agent_started"]
    assert len(starts) == 3
    assert starts[-1]["parent_agent_id"] == starts[1]["agent_id"]
    assert runtime._runs_by_id == {}


@pytest.mark.parametrize("outcome", ["failure", "cancellation"])
async def test_shared_runner_unregisters_ownership_after_interrupted_preparation(harness, monkeypatch, outcome):
    h = harness
    h.profile("parent", allow_spawn=True)
    runtime = h.manager
    entered = asyncio.Event()
    saved_tools = []

    async def prepare(*args, spawn_agent, **kwargs):
        saved_tools.append(spawn_agent)
        entered.set()
        if outcome == "failure":
            raise RuntimeError("preparation failed")
        await asyncio.Event().wait()

    monkeypatch.setattr(runtime._runner._factory, "prepare", prepare)
    task = asyncio.create_task(
        _run(runtime, AgentRunRequest(
                conversation_id="interrupted",
                profile_id="parent",
                message="prepare",
                attachments=None,
            ))
    )
    await asyncio.wait_for(entered.wait(), 5)
    if outcome == "cancellation":
        runtime.active_for_conversation("interrupted").cancel()
        assert (await task).status == "stopped"
    else:
        await task
    assert runtime._runs_by_id == {}
    with pytest.raises(RuntimeError, match="owning parent"):
        await saved_tools[0](instructions="stale", profile="parent")


async def test_child_preparation_failure_leaves_no_unpaired_spawn_or_registered_child(harness, monkeypatch):
    h = harness
    h.profile("parent", allow_spawn=True)
    h.profile("child", provider="", model="")
    runtime = h.manager
    provider = ObservedFakeProvider(runtime)
    monkeypatch.setattr("agent_runtime._factory.get_provider", lambda _: provider)

    await _run(runtime, AgentRunRequest(
        conversation_id="child-setup-failure", profile_id="parent", attachments=None,
        message=spawn(say("never executes"), profile="child", name="CHILD") + say("parent recovered"),
    ))

    events = load_events_jsonl("child-setup-failure")
    assert not any(e["type"] == "spawn_requested" for e in events)
    assert len([e for e in events if e["type"] == "agent_started"]) == 1
    results = [e for e in events if e["type"] == "tool_result"]
    assert len(results) == 1 and "not fully configured" in results[0]["content"]
    assert events[-1]["type"] == "agent_completed" and events[-1]["status"] == "success"
    assert runtime._runs_by_id == {}
