"""Tests for tasks._executor.

The executor resolves a task's agent profile before composing its agent.
``_profile_for`` must surface a missing or unknown profile as a clear
RuntimeError rather than failing confusingly downstream at routine-run time.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tasks._executor import TaskExecutor
from sdk.turn import ExecutionResult
from tasks._models import Routine, Run, Task, TaskResult


@asynccontextmanager
async def _null_scope(*_args, **_kwargs):
    yield


def _prepared_execution(monkeypatch: pytest.MonkeyPatch):
    store = MagicMock()
    run = Run(id="run-1", routine_id="routine-1")
    routine = Routine(id="routine-1", description="Test routine")
    task = Task(
        id="task-1",
        routine_id=routine.id,
        description="Test task",
        instruction="Do the test",
        agent_profile="profile-1",
    )
    task_result = TaskResult(id="result-1", run_id=run.id, task_id=task.id)
    store.get_run.return_value = run
    store.get_routine.return_value = routine

    history = MagicMock()
    history.drain_observers = AsyncMock()
    events_log = MagicMock()
    agent_capabilities = SimpleNamespace(tools=[])
    agent = SimpleNamespace(
        instruction="System prompt",
        context_window=1000,
        compaction_threshold=0.8,
        max_iterations=10,
        name="TASK_AGENT",
        provider="fake",
    )
    execute_mock = AsyncMock(return_value=ExecutionResult("success", "completed"))
    monkeypatch.setattr("tasks._executor.get_provider", lambda _: object())
    monkeypatch.setattr("tasks._executor.execution_context", lambda **_: object())
    cleanup_mock = AsyncMock()
    browser_runtime = MagicMock()
    browser_runtime.prepare_current_agent_browser = AsyncMock()

    monkeypatch.setattr(
        TaskExecutor,
        "_profile_for",
        lambda _self, _task: SimpleNamespace(id="profile-1", browser_profile_id="empty"),
    )
    monkeypatch.setattr("tasks._executor.build_agent_capabilities", AsyncMock(return_value=agent_capabilities))
    monkeypatch.setattr("tasks._executor.get_browser_runtime", lambda: browser_runtime)
    monkeypatch.setattr("tasks._executor.build_agent", lambda *_args, **_kwargs: agent)
    monkeypatch.setattr("tasks._executor.ConversationHistory", lambda **_kwargs: history)
    monkeypatch.setattr("tasks._executor.EventsLogWriter", lambda _conversation_id: events_log)
    monkeypatch.setattr("tasks._executor.ContextManager", lambda **_kwargs: object())
    monkeypatch.setattr("tasks._executor.LLMCompactionStrategy", lambda **_kwargs: object())
    monkeypatch.setattr("tasks._executor.default_hooks", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("tasks._executor.turn_scope", _null_scope)
    monkeypatch.setattr("tasks._executor.agent_span", _null_scope)
    monkeypatch.setattr("tasks._executor.publish_event", MagicMock())
    monkeypatch.setattr("tasks._executor.AgentExecutor.execute", execute_mock)
    monkeypatch.setattr("tasks._executor.run_conversation_exit_hooks", cleanup_mock)

    return TaskExecutor(store), task_result, task, execute_mock, cleanup_mock, history, browser_runtime


@pytest.mark.unit
def test_profile_for_raises_when_task_has_no_profile() -> None:
    task = Task(routine_id="g1", description="orphan task", instruction="do the thing", agent_profile=None)
    executor = TaskExecutor(store=None)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="no agent_profile"):
        executor._profile_for(task)


@pytest.mark.unit
def test_profile_for_raises_when_profile_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tasks._executor.get_agent_profile", lambda _id: None)
    task = Task(routine_id="g1", description="task", instruction="prompt", agent_profile="does_not_exist")
    executor = TaskExecutor(store=None)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="does_not_exist"):
        executor._profile_for(task)


@pytest.mark.unit
async def test_run_releases_conversation_after_success(monkeypatch: pytest.MonkeyPatch) -> None:
    executor, task_result, task, _execute, cleanup, history, browser_runtime = _prepared_execution(monkeypatch)

    result, file_paths = await executor.run(task_result, task)

    assert result == "completed"
    assert file_paths == []
    history.drain_observers.assert_awaited_once()
    browser_runtime.prepare_current_agent_browser.assert_awaited_once_with(
        agent_profile_id="profile-1",
        browser_profile_id="empty",
    )
    cleanup.assert_awaited_once_with("routines/routine-1/run-1/result-1")


@pytest.mark.unit
async def test_run_releases_conversation_after_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor, task_result, task, execute_mock, cleanup, _history, _runtime = _prepared_execution(monkeypatch)
    execute_mock.side_effect = RuntimeError("execution failed")

    with pytest.raises(RuntimeError, match="execution failed"):
        await executor.run(task_result, task)

    cleanup.assert_awaited_once_with("routines/routine-1/run-1/result-1")


@pytest.mark.unit
async def test_run_releases_conversation_after_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor, task_result, task, execute_mock, cleanup, _history, _runtime = _prepared_execution(monkeypatch)
    started = asyncio.Event()

    async def _blocked_run(*_args, **_kwargs):
        started.set()
        await asyncio.Event().wait()

    execute_mock.side_effect = _blocked_run
    execution = asyncio.create_task(executor.run(task_result, task))
    await started.wait()
    execution.cancel()

    with pytest.raises(asyncio.CancelledError):
        await execution

    cleanup.assert_awaited_once_with("routines/routine-1/run-1/result-1")


@pytest.mark.unit
async def test_run_releases_conversation_when_setup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MagicMock()
    run = Run(id="run-1", routine_id="routine-1")
    routine = Routine(id="routine-1", description="Test routine")
    task = Task(
        id="task-1",
        routine_id=routine.id,
        description="Test task",
        instruction="Do the test",
        agent_profile=None,
    )
    task_result = TaskResult(id="result-1", run_id=run.id, task_id=task.id)
    store.get_run.return_value = run
    store.get_routine.return_value = routine
    cleanup = AsyncMock()
    monkeypatch.setattr("tasks._executor.run_conversation_exit_hooks", cleanup)

    with pytest.raises(RuntimeError, match="no agent_profile"):
        await TaskExecutor(store).run(task_result, task)

    cleanup.assert_awaited_once_with("routines/routine-1/run-1/result-1")


@pytest.mark.unit
async def test_run_releases_conversation_when_observer_drain_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor, task_result, task, _execute, cleanup, history, _runtime = _prepared_execution(monkeypatch)
    history.drain_observers.side_effect = RuntimeError("drain failed")

    with pytest.raises(RuntimeError, match="drain failed"):
        await executor.run(task_result, task)

    cleanup.assert_awaited_once_with("routines/routine-1/run-1/result-1")
