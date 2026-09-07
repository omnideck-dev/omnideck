"""Routine adapter behavior at the shared AgentRuntime boundary."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents import AgentProfile
from agent_runtime import RunResult
from agent_core.events import FileOutputPayload
from agent_core.providers import TokenUsage
from agent_core.turn import ExecutionResult, ToolLoopError
from tasks._executor import TaskExecutor
from tasks._models import Routine, Run, Task, TaskResult


def prepared(monkeypatch):
    store, runtime, handle = MagicMock(), MagicMock(), MagicMock()
    store.get_run.return_value = Run(id="workflow-run", routine_id="routine")
    store.get_routine.return_value = Routine(id="routine", description="Routine purpose")
    task = Task(id="task", routine_id="routine", description="Task", instruction="Do the task", agent_profile="profile")
    task_result = TaskResult(id="result", run_id="workflow-run", task_id="task")
    runtime.start = AsyncMock(return_value=handle)
    handle.run_id = "agent-run"
    handle.wait = AsyncMock(return_value=RunResult(
        "agent-run", "routines/routine/workflow-run/result", ExecutionResult("success", "completed"), TokenUsage(),
        (FileOutputPayload(type="file_output", filename="proof.txt", content_type="text/plain", path="/proof.txt"),), (),
    ))
    monkeypatch.setattr("tasks._executor.get_agent_profile", lambda _: AgentProfile(id="profile", name="Profile", model="model"))
    return TaskExecutor(store, runtime), task_result, task, store, runtime, handle


async def test_run_uses_shared_runtime_and_maps_result_and_files(monkeypatch):
    executor, result, task, store, runtime, handle = prepared(monkeypatch)
    assert await executor.run(result, task) == ("completed", ["/proof.txt"])
    request = runtime.start.await_args.args[0]
    assert "Routine purpose" in request.message and "Do the task" in request.message
    assert request.policy.agent_name == "TASK_AGENT"
    assert request.policy.conversation_lifetime == "run"
    assert not request.policy.restore_skills and not request.policy.persist_skills and not request.policy.include_memory
    store.set_agent_run.assert_called_once_with("result", conversation_id=request.conversation_id, agent_run_id="agent-run")
    handle.cancel.assert_not_called()


async def test_run_raises_typed_execution_failure(monkeypatch):
    executor, result, task, store, runtime, handle = prepared(monkeypatch)
    handle.wait.return_value = RunResult("agent-run", "conversation", ExecutionResult("error", error="provider failed"), TokenUsage(), (), ())
    with pytest.raises(ToolLoopError, match="provider failed"):
        await executor.run(result, task)


async def test_routine_cancellation_explicitly_cancels_owned_run_and_awaits_cleanup(monkeypatch):
    executor, result, task, store, runtime, handle = prepared(monkeypatch)
    started = asyncio.Event()
    completion = handle.wait.return_value
    calls = 0

    async def wait():
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await asyncio.Event().wait()
        return completion

    handle.wait.side_effect = wait
    owner = asyncio.create_task(executor.run(result, task))
    await started.wait()
    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner
    handle.cancel.assert_called_once_with()
    assert calls == 2


async def test_failed_run_metadata_write_cancels_owned_execution(monkeypatch):
    executor, result, task, store, runtime, handle = prepared(monkeypatch)
    store.set_agent_run.side_effect = RuntimeError("store failed")
    with pytest.raises(RuntimeError, match="store failed"):
        await executor.run(result, task)
    handle.cancel.assert_called_once_with()
    handle.wait.assert_awaited_once()


@pytest.mark.parametrize("profile", [None, "missing"])
def test_profile_for_rejects_missing_configuration(monkeypatch, profile):
    monkeypatch.setattr("tasks._executor.get_agent_profile", lambda _: None)
    task = Task(routine_id="routine", description="Task", instruction="Work", agent_profile=profile)
    with pytest.raises(RuntimeError, match="no agent_profile" if profile is None else "not found"):
        TaskExecutor(MagicMock(), MagicMock())._profile_for(task)
