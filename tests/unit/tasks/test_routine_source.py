"""The routine source runs, retries, notifies and deletes its own tasks."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from config import NotificationsConfig, RoutinesConfig
from tasks import RoutineWorkSource
from tasks._file_store import FileTaskStore

NOW = datetime(2026, 11, 18, tzinfo=timezone.utc)


class Executor:
    def __init__(self, failures: int = 0, hold: bool = False):
        self.failures = failures
        self.hold = hold
        self.calls = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def run(self, result, task):
        self.calls += 1
        self.entered.set()
        if self.hold:
            await self.release.wait()
        if self.calls <= self.failures:
            raise RuntimeError("The service was unavailable")
        return f"Finished {task.description}", []


class Notifier:
    def __init__(self):
        self.sent: list[str] = []

    async def send(self, message, files=None):
        self.sent.append(message)


def source_for(tmp_path, executor, *, notifier=None, notifications=None):
    store = FileTaskStore(tmp_path / "routines")
    config = RoutinesConfig(notifications=notifications or NotificationsConfig(enabled=True))
    return store, RoutineWorkSource(store, executor, config, max_concurrent=3, notifier=notifier)


def queue(store, *, max_retries=0):
    routine = store.create_routine("Morning digest", auto_run=False)
    store.create_tasks(routine.id, [{"description": "Summarize email", "instruction": "Summarize my email",
                                     "agent_profile": "leaf", "max_retries": max_retries}])
    return routine, store.queue_run(routine.id)


async def run_until_done(source, store, run):
    for _ in range(20):
        for work in source.pending(NOW):
            completion = await work.dispatch()
            if completion is not None:
                await completion
        if store.get_run(run.id).status in {"completed", "failed"}:
            return store.get_run(run.id).status
    raise AssertionError("The run did not finish")


async def test_failed_task_retries_and_the_run_completes(tmp_path):
    store, source = source_for(tmp_path, Executor(failures=1))
    _routine, run = queue(store, max_retries=1)
    assert await run_until_done(source, store, run) == "completed"
    assert store.get_task_results(run.id)[0].retry_count == 1


async def test_task_that_fails_twice_fails_the_run(tmp_path):
    store, source = source_for(tmp_path, Executor(failures=2))
    _routine, run = queue(store, max_retries=1)
    assert await run_until_done(source, store, run) == "failed"


async def test_completed_run_sends_one_notice(tmp_path):
    notifier = Notifier()
    store, source = source_for(tmp_path, Executor(), notifier=notifier)
    _routine, run = queue(store)
    await run_until_done(source, store, run)
    assert len(notifier.sent) == 1


async def test_failed_run_sends_one_failed_notice(tmp_path):
    notifier = Notifier()
    store, source = source_for(tmp_path, Executor(failures=1), notifier=notifier)
    _routine, run = queue(store)
    await run_until_done(source, store, run)
    assert len(notifier.sent) == 1 and "Summarize email" in notifier.sent[0]


@pytest.mark.parametrize("failures", [0, 1])
async def test_notice_turned_off_sends_nothing(tmp_path, failures):
    notifier = Notifier()
    notifications = NotificationsConfig(enabled=True, on_run_completed=False, on_run_failed=False)
    store, source = source_for(tmp_path, Executor(failures=failures), notifier=notifier, notifications=notifications)
    _routine, run = queue(store)
    await run_until_done(source, store, run)
    assert notifier.sent == []


async def test_retry_sends_no_notice(tmp_path):
    notifier = Notifier()
    store, source = source_for(tmp_path, Executor(failures=1), notifier=notifier)
    _routine, run = queue(store, max_retries=1)
    [work] = source.pending(NOW)
    await (await work.dispatch())
    assert store.get_task_results(run.id)[0].status == "pending"
    assert notifier.sent == []


async def test_delete_blocks_and_awaits_routine_tasks(tmp_path):
    executor = Executor(hold=True)
    store, source = source_for(tmp_path, executor)
    routine, _run = queue(store)
    [work] = source.pending(NOW)
    execution = await work.dispatch()
    await executor.entered.wait()
    async with source.stop_routine(routine.id):
        assert execution.done()
        assert source.pending(NOW) == []
        assert source.status["active_tasks"] == 0


async def test_task_admitted_in_the_same_tick_as_a_delete_starts_no_agent(tmp_path):
    executor = Executor()
    store, source = source_for(tmp_path, executor)
    routine, _run = queue(store)
    [work] = source.pending(NOW)
    async with source.stop_routine(routine.id):
        assert await work.dispatch() is None
    assert executor.calls == 0


async def test_status_counts_own_tasks_with_the_routine_limit(tmp_path):
    executor = Executor(hold=True)
    store, source = source_for(tmp_path, executor)
    routine, _run = queue(store)
    [work] = source.pending(NOW)
    execution = await work.dispatch()
    await executor.entered.wait()
    status = source.status
    assert status == {"paused": False, "active_tasks": 1, "max_concurrent": 3, "running_routine_ids": [routine.id]}
    executor.release.set()
    await execution
    assert source.status["active_tasks"] == 0
