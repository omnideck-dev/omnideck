"""Exercise durable wake admission and goal runtime ownership."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_core.turn import ExecutionResult
from agent_runtime import AgentRunRequest, AgentRuntime, GoalRunTrigger, RunSession
from goals._scheduler import GoalScheduler
from goals._store import GoalStore


class GoalRunner:
    def __init__(self) -> None:
        self.requests: list[AgentRunRequest] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.result = ExecutionResult("success", output="I have completed everything.")

    async def run(self, request: AgentRunRequest, session: RunSession) -> ExecutionResult:
        self.requests.append(request)
        self.entered.set()
        await self.release.wait()
        if session.stop_event.is_set():
            return ExecutionResult("stopped")
        return self.result


@pytest.fixture
def store(tmp_path: Path) -> GoalStore:
    return GoalStore(tmp_path / "goals")


async def test_final_text_never_completes_or_requeues_goal(store: GoalStore) -> None:
    goal = store.create("goal-chat", "Organize a household move", "profile")
    runner = GoalRunner()
    runtime = AgentRuntime(runner, goal_store=store)
    scheduler = GoalScheduler(store, runtime)
    try:
        await scheduler.tick()
        handle = runtime.active_for_conversation(goal.conversation_id)
        assert handle is not None
        await handle.wait()
        await scheduler.tick()
        current = store.get(goal.id)
        assert current is not None
        assert current.status == "active"
        assert current.wake_id is None and current.claimed_run_id is None
        assert current.last_run_id == handle.run_id
        assert len(runner.requests) == 1
        trigger = runner.requests[0].goal_trigger
        assert trigger is not None and trigger.goal_id == goal.id
    finally:
        await runtime.close()


async def test_busy_chat_preserves_pending_wake_and_runs_once_when_free(store: GoalStore) -> None:
    goal = store.create("goal-chat", "Plan meals", "profile")
    runner = GoalRunner()
    runner.release.clear()
    runtime = AgentRuntime(runner, goal_store=store, goals_enabled=lambda: False)
    scheduler = GoalScheduler(store, runtime)
    try:
        user = await runtime.start(AgentRunRequest(goal.conversation_id, "hello", None, "profile"))
        await runner.entered.wait()
        await scheduler.tick()
        assert store.get(goal.id).wake_id == goal.wake_id
        runner.release.set()
        await user.wait()
        # A second runtime represents the same conversation after its owner exits.
        await runtime.close()
        runtime = AgentRuntime(runner, goal_store=store)
        scheduler = GoalScheduler(store, runtime)
        await asyncio.gather(scheduler.tick(), scheduler.tick())
        handle = runtime.active_for_conversation(goal.conversation_id)
        if handle is not None:
            await handle.wait()
        assert len(runner.requests) == 2
        assert store.get(goal.id).wake_id is None
    finally:
        runner.release.set()
        await runtime.close()


async def test_pause_after_admission_revokes_wake_before_runner_starts(store: GoalStore) -> None:
    goal = store.create("goal-chat", "Plan a trip", "profile")
    runner = GoalRunner()
    runtime = AgentRuntime(runner, goal_store=store)
    scheduler = GoalScheduler(store, runtime)
    try:
        await scheduler.tick()
        handle = runtime.active_for_conversation(goal.conversation_id)
        assert handle is not None
        store.pause(goal.id)
        result = await handle.wait()
        assert result.status == "stopped"
        assert runner.requests == []
        assert store.get(goal.id).status == "paused"
    finally:
        await runtime.close()


async def test_future_wake_and_disabled_feature_do_not_dispatch(store: GoalStore) -> None:
    goal = store.create("goal-chat", "Track a delivery", "profile")
    due = datetime.now(timezone.utc) + timedelta(hours=1)
    store.schedule(goal.id, due.isoformat(), "Check delivery", "Read tracking update")
    runner = GoalRunner()
    runtime = AgentRuntime(runner, goal_store=store)
    enabled = False
    scheduler = GoalScheduler(store, runtime, enabled=lambda: enabled)
    try:
        await scheduler.tick(due + timedelta(seconds=1))
        enabled = True
        await scheduler.tick(due - timedelta(seconds=1))
        assert runner.requests == []
        await scheduler.tick(due + timedelta(seconds=1))
        handle = runtime.active_for_conversation(goal.conversation_id)
        assert handle is not None
        await handle.wait()
        assert len(runner.requests) == 1
    finally:
        await runtime.close()


async def test_explicit_continuation_survives_previous_run_finish(store: GoalStore) -> None:
    goal = store.create("goal-chat", "Organize recipes", "profile")
    runner = GoalRunner()
    runner.release.clear()
    runtime = AgentRuntime(runner, goal_store=store)
    scheduler = GoalScheduler(store, runtime)
    try:
        await scheduler.tick()
        first = runtime.active_for_conversation(goal.conversation_id)
        assert first is not None
        await runner.entered.wait()
        current = store.get(goal.id)
        assert current is not None
        store.schedule(goal.id, datetime.now(timezone.utc).isoformat(), "More work", "Sort remaining recipes",
                       claim_id=current.claimed_run_id, immediate=True)
        await scheduler.tick()
        assert len(runner.requests) == 1
        runner.release.set()
        await first.wait()
        await scheduler.tick()
        second = runtime.active_for_conversation(goal.conversation_id)
        assert second is not None
        await second.wait()
        assert len(runner.requests) == 2
    finally:
        runner.release.set()
        await runtime.close()


async def test_shutdown_leaves_claim_for_one_reconciliation_wake(store: GoalStore) -> None:
    goal = store.create("goal-chat", "Arrange appointments", "profile")
    runner = GoalRunner()
    runner.release.clear()
    runtime = AgentRuntime(runner, goal_store=store, shutdown_timeout=0.01)
    scheduler = GoalScheduler(store, runtime)
    await scheduler.tick()
    await runner.entered.wait()
    await runtime.close()
    assert store.get(goal.id).claimed_run_id is not None
    recovered = store.recover_claims()
    assert len(recovered) == 1
    assert "inspect saved progress" in recovered[0].next_action
    assert recovered[0].wake_id is not None
    assert store.recover_claims() == []


async def test_failed_run_waits_for_input_without_inventing_retry(store: GoalStore) -> None:
    goal = store.create("goal-chat", "Find an appointment", "profile")
    runner = GoalRunner()
    runner.result = ExecutionResult("error", error="Provider unavailable")
    runtime = AgentRuntime(runner, goal_store=store)
    scheduler = GoalScheduler(store, runtime)
    try:
        await scheduler.tick()
        handle = runtime.active_for_conversation(goal.conversation_id)
        assert handle is not None
        await handle.wait()
        await scheduler.tick()
        current = store.get(goal.id)
        assert current.status == "needs_input"
        assert current.status_reason == "Provider unavailable"
        assert len(runner.requests) == 1
    finally:
        await runtime.close()


async def test_admission_conflict_restores_the_same_pending_wake(store, monkeypatch):
    from agent_runtime import RunConflictError

    goal = store.create("goal-chat", "Organize a calendar", "profile")
    runtime = AgentRuntime(GoalRunner(), goal_store=store)

    async def conflict(_request):
        raise RunConflictError("The user started a turn")

    monkeypatch.setattr(runtime, "start", conflict)
    try:
        await GoalScheduler(store, runtime).tick()
        current = store.get(goal.id)
        assert current.wake_id == goal.wake_id
        assert current.claimed_run_id is None
    finally:
        await runtime.close()
