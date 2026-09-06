"""Exercise scheduling, task execution, delegation, and file-backed results."""

import asyncio
import json

import pytest

from conversations import load_events_jsonl
from sdk.events import AgentEvent, FileOutputPayload, publish_event
from sdk.providers import ProviderError
from tasks import TaskExecutor, TaskRunner
from tasks._file_store import FileTaskStore

from ._support import call, reply


async def wait_for_terminal(store, run_id):
    async def wait():
        while store.get_run(run_id).status not in ("completed", "failed"):
            await asyncio.sleep(0.01)
    await asyncio.wait_for(wait(), 5)


@pytest.mark.parametrize("fail_first", [False, True], ids=["dependency-success", "dependency-failure"])
async def test_routine_scheduler_executes_only_ready_tasks_and_persists_outcomes(harness, fail_first):
    h = harness
    output = h.home / "routine.txt"

    async def write_proof() -> str:
        output.write_text("routine proof")
        publish_event(AgentEvent(payload=FileOutputPayload(
            type="file_output", filename=output.name, content_type="text/plain", path=str(output),
        )))
        return "proof saved"

    h.skill("writer", write_proof)
    h.profile("first", allow_spawn=True)
    h.profile("worker", skills=["writer"])
    h.profile("second")
    if fail_first:
        h.provider.plan("first", ProviderError("unavailable", retryable=False))
    else:
        h.provider.plan("first", reply(calls=[
            call("spawn_agent", profile="worker", agent_name="WORKER", instructions="make proof"),
        ]), reply("predecessor result"))
        h.provider.plan("worker", reply(calls=[call("write_proof")]), reply("worker result"))
        h.provider.plan("second", reply("dependent result"))
    routine = h.store.create_routine("routine objective", auto_run=False)
    first = h.store.create_tasks(routine.id, [{
        "description": "First task", "instruction": "first instruction", "agent_profile": "first", "max_retries": 0,
    }])[0]
    second = h.store.create_tasks(routine.id, [{
        "description": "Second task", "instruction": "second instruction", "agent_profile": "second",
        "depends_on": [first.id], "max_retries": 0,
    }])[0]
    run = h.store.queue_run(routine.id)
    config = h.config.routines.model_copy(update={"poll_interval": 0.01, "max_concurrent": 2})
    runner = TaskRunner(h.store, TaskExecutor(h.store, h.manager), config)
    try:
        await runner.start()
        await wait_for_terminal(h.store, run.id)
    finally:
        await runner.stop()

    # Reopen the store so assertions cover committed disk state.
    store = FileTaskStore(h.store._base)
    results = {r.task_id: r for r in store.get_task_results(run.id)}
    assert store.get_run(run.id).status == ("failed" if fail_first else "completed")
    first_result = results[first.id]
    assert first_result.conversation_id in h.exited_conversations
    first_events = load_events_jsonl(first_result.conversation_id)
    assert first_events[-1]["type"] == "agent_completed"
    assert len([e for e in first_events if e["type"] == "user_message" and e["agent_name"] == "TASK_AGENT"]) == 1
    if fail_first:
        assert first_result.status == "failed"
        assert "unavailable" in first_result.error
        assert not any(r["model"] == "second" for r in h.provider.requests)
        assert results[second.id].status == "failed"
        assert results[second.id].error == "Blocked: a dependency task failed"
        assert len([e for e in first_events if e["type"] == "error"]) == 1
    else:
        assert first_result.result == "predecessor result"
        assert first_result.file_outputs == [str(output)]
        assert output.read_text() == "routine proof"
        assert results[second.id].result == "dependent result"
        assert results[second.id].conversation_id != first_result.conversation_id
        second_request = next(r for r in h.provider.requests if r["model"] == "second")
        user = next(m["content"] for m in second_request["messages"] if m["role"] == "user")
        assert "routine objective" in user and "second instruction" in user
        assert "First task" in user and "predecessor result" in user
        assert "worker result" not in json.dumps(second_request["messages"])
        assert len(h.exited_conversations) == 2
        assert len(h.exited_agents) == 3
        assert len([e for e in first_events if e["type"] == "file_output"]) == 1
