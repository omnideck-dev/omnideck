"""Run ownership, completion, and control using real FakeProvider executions."""

import asyncio

import pytest

from agent_runtime import AgentRunRequest
from conversations import get_or_create_conversation, load_events_jsonl
from providers._fake import FakeProvider
from agent_core.events import AgentEvent, FileOutputPayload, publish_event
from agent_core.providers import ChatResponse, TokenUsage
from agent_core.turn import get_execution_context
from tasks import TaskExecutor
from tests.e2e._protocol import call_tool, say, spawn


def use_fake(monkeypatch, provider=None):
    provider = provider if provider is not None else FakeProvider()
    monkeypatch.setattr("agent_runtime._factory.get_provider", lambda _: provider)
    return provider


def request(conversation, prompt, profile="leaf"):
    return AgentRunRequest(conversation_id=conversation, message=prompt, attachments=None, profile_id=profile)


async def test_cancelling_a_waiter_does_not_cancel_the_runtime_owned_execution(harness, monkeypatch):
    h = harness
    use_fake(monkeypatch)
    reached, release = asyncio.Event(), asyncio.Event()

    async def pause() -> str:
        """Pause until the observer has detached."""
        reached.set()
        await release.wait()
        return "released"

    h.skill("pause", pause)
    h.profile(skills=["pause"])
    handle = await h.manager.start(request("detached", call_tool("pause") + say("still completed")))
    await asyncio.wait_for(reached.wait(), 5)
    observer = asyncio.create_task(handle.wait())
    await asyncio.sleep(0)
    observer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await observer
    assert h.manager.get(handle.run_id) is not None
    assert not handle._session.stop_event.is_set()
    release.set()
    result = await asyncio.wait_for(handle.wait(), 5)
    assert result.output == "still completed" and result.status == "success"
    records = [r async for r in handle.events()]
    assert records[-1].event.payload.type == "turn_end"
    assert sum(r.event.payload.type == "turn_end" for r in records) == 1
    assert h.manager.get(handle.run_id) is None
    assert handle._session.executions == {}
    history = await get_or_create_conversation("detached")
    assert history._observers == []


async def test_result_aggregates_child_usage_and_file_artifacts_once(harness, monkeypatch):
    h = harness

    class MeteredFake(FakeProvider):
        async def chat_stream(self, **kwargs):
            async for chunk in super().chat_stream(**kwargs):
                if isinstance(chunk, ChatResponse):
                    chunk = chunk.model_copy(update={"usage": TokenUsage(prompt_tokens=10, completion_tokens=2)})
                yield chunk

    use_fake(monkeypatch, MeteredFake())
    path = h.home / "proof.txt"

    async def write_proof() -> str:
        """Write and publish a real child-owned artifact."""
        path.write_text("artifact proof")
        publish_event(
            AgentEvent(
                payload=FileOutputPayload(
                    type="file_output", path=str(path), filename=path.name, content_type="text/plain"
                )
            )
        )
        return "proof saved"

    h.skill("proof", write_proof)
    h.profile("root", allow_spawn=True)
    h.profile("leaf", skills=["proof"])
    prompt = spawn(call_tool("write_proof") + say("child output"), profile="leaf", name="CHILD") + say("root output")
    handle = await h.manager.start(request("aggregate", prompt, "root"))
    result = await handle.wait()
    assert result.output == "root output"
    assert result.usage.prompt_tokens == 40 and result.usage.completion_tokens == 8
    assert len(result.executions) == 2
    assert sorted(r.usage.prompt_tokens for _, r in result.executions) == [20, 20]
    assert [a.path for a in result.artifacts] == [str(path)]
    assert path.read_text() == "artifact proof"
    assert handle._session.executions == {}


async def test_nudges_are_restricted_to_the_handle_owning_the_execution(harness, monkeypatch):
    h = harness
    use_fake(monkeypatch)
    entered = {name: asyncio.Event() for name in ("left", "right")}
    release = asyncio.Event()

    async def pause() -> str:
        """Hold two runs active while their controls are exercised."""
        entered[get_execution_context().conversation_id].set()
        await release.wait()
        return "released"

    h.skill("pause", pause)
    h.profile(skills=["pause"])
    left = await h.manager.start(request("left", call_tool("pause") + say("old left")))
    right = await h.manager.start(request("right", call_tool("pause") + say("right unchanged")))
    await asyncio.wait_for(asyncio.gather(*(e.wait() for e in entered.values())), 5)
    with pytest.raises(ValueError, match="No active execution"):
        left.nudge("wrong run", execution_id=right._session.root_context.execution_id)
    left.nudge(say("updated left"))
    release.set()
    left_result, right_result = await asyncio.gather(left.wait(), right.wait())
    assert left_result.output == "updated left"
    assert right_result.output == "right unchanged"
    assert len([e for e in load_events_jsonl("left") if e.get("is_nudge")]) == 1
    assert not any(e.get("is_nudge") for e in load_events_jsonl("right"))
    with pytest.raises(ValueError, match="No active execution"):
        left.nudge("too late")


async def test_routine_cancellation_stops_owned_agent_and_releases_session_resources(harness, monkeypatch):
    h = harness
    use_fake(monkeypatch)
    entered = asyncio.Event()

    async def pause() -> str:
        """Hold the routine execution until its owner cancels it."""
        entered.set()
        await asyncio.Event().wait()
        return "unreachable"

    h.skill("pause", pause)
    h.profile(skills=["pause"])
    routine = h.store.create_routine("cancellation", auto_run=False)
    task = h.store.create_task(routine.id, "pause", call_tool("pause") + say("unreachable"), agent_profile="leaf")
    workflow = h.store.queue_run(routine.id)
    task_result = h.store.get_task_results(workflow.id)[0]
    owner = asyncio.create_task(TaskExecutor(h.store, h.manager).run(task_result, task))
    await asyncio.wait_for(entered.wait(), 5)
    stored = h.store.get_task_results(workflow.id)[0]
    handle = h.manager.get(stored.agent_run_id)
    assert handle is not None and stored.agent_run_id != workflow.id
    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner
    assert (await handle.wait()).status == "stopped"
    assert h.manager.active_for_conversation(stored.conversation_id) is None
    assert h.exited_conversations == [stored.conversation_id]
    assert handle._session.executions == {}
    assert handle._session.history._observers == []
    events = load_events_jsonl(stored.conversation_id)
    assert events[-1]["type"] == "agent_completed" and events[-1]["status"] == "stopped"
    records = [r async for r in handle.events()]
    assert records[-1].event.payload.type == "turn_end"
    assert sum(r.event.payload.type == "turn_end" for r in records) == 1


async def test_cancellation_before_task_scheduling_does_not_leak_admission(harness, monkeypatch):
    h = harness
    h.profile()

    def unexpected_provider(_):
        raise AssertionError("Early cancellation must skip provider setup")

    monkeypatch.setattr("agent_runtime._factory.get_provider", unexpected_provider)
    handle = await h.manager.start(request("early-cancel", say("never")))
    handle.cancel()
    result = await handle.wait()
    assert result.status == "stopped"
    assert h.manager.active_for_conversation("early-cancel") is None
    assert handle._session.executions == {}
    assert [r.event.payload.type async for r in handle.events()] == ["turn_end"]
