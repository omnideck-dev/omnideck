"""Turning Goals off stops every goal run and chat turn and leaves every goal as it was."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from agent_core.turn import ExecutionResult
from agent_runtime import AgentRunRequest, AgentRuntime, RunSession
from goals import GoalRunExtension, GoalStore, GoalWorkSource, stop_goal_runs
from scheduling import Scheduler

from tests.unit.goals.support import completed, create, scheduled, waiting


class StoppableRunner:
    """Runs until the run is asked to stop."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()

    async def run(self, request: AgentRunRequest, session: RunSession) -> ExecutionResult:
        self.entered.set()
        await session.stop_event.wait()
        return ExecutionResult("stopped")


@pytest.fixture
async def setup(tmp_path):
    enabled = {"value": True}
    store = GoalStore(tmp_path / "goals")
    runner = StoppableRunner()
    runtime = AgentRuntime(runner, extensions=[GoalRunExtension(store, enabled=lambda: enabled["value"])])
    yield store, runtime, runner, enabled
    await runtime.close()


def turn_off(store, runtime, enabled):
    enabled["value"] = False
    stop_goal_runs(store, runtime)


async def test_turn_off_keeps_goal_state(setup):
    store, runtime, _runner, enabled = setup
    later = scheduled(store, create(store, "later"))
    asking = waiting(store, create(store, "asking"))
    turn_off(store, runtime, enabled)
    assert store.get(later.id) == later
    assert store.get(asking.id) == asking


async def test_turn_off_marks_wake_run_interrupted(setup):
    store, runtime, runner, enabled = setup
    goal = create(store)
    scheduler = Scheduler(max_concurrent=2, poll_interval=0.01, shutdown_timeout=0)
    scheduler.register(GoalWorkSource(store, runtime, enabled=lambda: enabled["value"]))
    await scheduler.tick()
    await runner.entered.wait()
    handle = runtime.active_for_conversation(goal.conversation_id)
    assert store.get(goal.id).claim.wake_id == goal.next.id
    turn_off(store, runtime, enabled)
    assert (await handle.wait()).status == "stopped"
    current = store.get(goal.id)
    assert current.claim is None
    assert current.next.id == goal.next.id and current.next.reason == "interrupted"
    assert current.paused is False
    enabled["value"] = True
    assert [item.id for item in store.due()] == [goal.id]


async def test_turn_off_stops_a_chat_turn_and_leaves_its_goal_unchanged(setup):
    store, runtime, runner, enabled = setup
    goal = waiting(store, create(store))
    handle = await runtime.start(AgentRunRequest("chat", "How is it going?", None, "assistant"))
    await runner.entered.wait()
    assert store.get(goal.id).claim is not None
    turn_off(store, runtime, enabled)
    assert (await handle.wait()).status == "stopped"
    current = store.get(goal.id)
    assert current.claim is None and current.next == goal.next
    assert current.revision == goal.revision and current.paused is False


async def test_turn_off_reads_no_goal_files(setup, monkeypatch):
    store, runtime, runner, enabled = setup
    goal = create(store)
    handle = await runtime.start(AgentRunRequest("chat", "Hi", None, "assistant"))
    await runner.entered.wait()
    for index in range(3):
        completed(store, create(store, f"done-{index}"))
    reads: list[Path] = []
    original = Path.read_text

    def counted(path, *args, **kwargs):
        reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted)
    turn_off(store, runtime, enabled)
    assert all(goal.id in str(path) for path in reads)
    monkeypatch.undo()
    assert (await handle.wait()).status == "stopped"


async def test_turn_off_stops_a_run_when_an_ended_goal_file_is_unreadable(setup, caplog):
    store, runtime, runner, enabled = setup
    ended = completed(store, create(store, "old"))
    broken = store._base / "old" / "goals" / ended.id / "goal.json"
    broken.write_text("{")
    goal = create(store)
    handle = await runtime.start(AgentRunRequest("chat", "Hi", None, "assistant"))
    await runner.entered.wait()
    with caplog.at_level(logging.ERROR):
        turn_off(store, runtime, enabled)
    assert (await handle.wait()).status == "stopped"
    assert store.get(goal.id).claim is None
