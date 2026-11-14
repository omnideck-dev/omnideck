"""Durable wake admission and goal run ownership through the shared scheduler."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_core.turn import ExecutionResult
from agent_runtime import AgentRunRequest, AgentRuntime, RunSession
from goals import GoalStep
from goals._scheduling import GoalWorkSource
from goals._store import GoalStore
from scheduling import Scheduler

from tests.unit.goals.support import choose, create, failed, scheduled, with_plan


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


def make_scheduler(store: GoalStore, runtime: AgentRuntime, enabled=lambda: True) -> Scheduler:
    scheduler = Scheduler(max_concurrent=2, poll_interval=0.01, shutdown_timeout=0)
    scheduler.register(GoalWorkSource(store, runtime, enabled=enabled))
    return scheduler


async def test_final_text_never_completes_the_goal_and_the_goal_waits(store: GoalStore) -> None:
    goal = create(store, "goal-chat")
    runner = GoalRunner()
    runtime = AgentRuntime(runner, goal_store=store)
    scheduler = make_scheduler(store, runtime)
    try:
        await scheduler.tick()
        handle = runtime.active_for_conversation(goal.conversation_id)
        assert handle is not None
        await handle.wait()
        await scheduler.tick()
        current = store.get(goal.id)
        assert current.next.kind == "wait" and current.next.question_ids == []
        assert current.claim is None
        assert current.last_run_id == handle.run_id
        assert len(runner.requests) == 1
        trigger = runner.requests[0].goal_trigger
        assert trigger is not None and trigger.goal_id == goal.id
        assert trigger.wake_id == goal.next.id and trigger.reason == "planned"
    finally:
        await runtime.close()


async def test_wake_run_names_the_step_in_progress(store: GoalStore) -> None:
    goal = with_plan(store, create(store, "goal-chat"),
                     GoalStep(id="guests", title="Collect the guest list", status="done"),
                     GoalStep(id="book", title="Book the park pavilion", status="in_progress"))
    runner = GoalRunner()
    runtime = AgentRuntime(runner, goal_store=store)
    try:
        await make_scheduler(store, runtime).tick()
        await runtime.active_for_conversation(goal.conversation_id).wait()
        trigger = runner.requests[0].goal_trigger
        assert trigger.step == "Book the park pavilion"
        assert runner.requests[0].message == "Book the park pavilion"
    finally:
        await runtime.close()


async def test_busy_chat_keeps_the_wake_and_runs_once_when_free(store: GoalStore) -> None:
    goal = create(store, "goal-chat")
    runner = GoalRunner()
    runner.release.clear()
    runtime = AgentRuntime(runner, goal_store=store, goals_enabled=lambda: False)
    scheduler = make_scheduler(store, runtime)
    try:
        user = await runtime.start(AgentRunRequest(goal.conversation_id, "hello", None, "profile"))
        await runner.entered.wait()
        await scheduler.tick()
        assert store.get(goal.id).next == goal.next
        assert store.get(goal.id).claim is None
        runner.release.set()
        await user.wait()
        await runtime.close()
        runtime = AgentRuntime(runner, goal_store=store)
        scheduler = make_scheduler(store, runtime)
        await asyncio.gather(scheduler.tick(), scheduler.tick())
        handle = runtime.active_for_conversation(goal.conversation_id)
        if handle is not None:
            await handle.wait()
        assert len(runner.requests) == 2
        assert store.get(goal.id).next.kind == "wait"
    finally:
        runner.release.set()
        await runtime.close()


async def test_pause_after_admission_stops_the_run_and_keeps_the_wake(store: GoalStore) -> None:
    goal = create(store, "goal-chat")
    runner = GoalRunner()
    runtime = AgentRuntime(runner, goal_store=store)
    try:
        await make_scheduler(store, runtime).tick()
        handle = runtime.active_for_conversation(goal.conversation_id)
        assert handle is not None
        store.pause(goal.id)
        result = await handle.wait()
        assert result.status == "stopped"
        assert runner.requests == []
        current = store.get(goal.id)
        assert current.paused and current.claim is None
        assert current.next.id == goal.next.id and current.next.reason == "interrupted"
    finally:
        await runtime.close()


async def test_future_wake_and_disabled_feature_do_not_dispatch(store: GoalStore) -> None:
    due = datetime.now(timezone.utc) + timedelta(hours=1)
    goal = scheduled(store, create(store, "goal-chat"), at=due.isoformat())
    runner = GoalRunner()
    runtime = AgentRuntime(runner, goal_store=store)
    enabled = False
    scheduler = make_scheduler(store, runtime, enabled=lambda: enabled)
    try:
        await scheduler.tick(due + timedelta(seconds=1))
        assert store.get(goal.id).claim is None
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


async def test_scheduler_does_not_claim_due_goals_while_goals_are_off(store: GoalStore) -> None:
    goal = create(store, "goal-chat")
    runner = GoalRunner()
    runtime = AgentRuntime(runner, goal_store=store)
    scheduler = make_scheduler(store, runtime, enabled=lambda: False)
    try:
        await scheduler.tick()
        await scheduler.tick()
        assert runtime.active_for_conversation(goal.conversation_id) is None
        assert store.get(goal.id).claim is None
        assert store.get(goal.id) == goal
        assert runner.requests == []
    finally:
        await runtime.close()


async def test_continue_chosen_during_a_run_runs_again_after_it(store: GoalStore) -> None:
    goal = with_plan(store, create(store, "goal-chat"))
    runner = GoalRunner()
    runner.release.clear()
    runtime = AgentRuntime(runner, goal_store=store)
    scheduler = make_scheduler(store, runtime)
    try:
        await scheduler.tick()
        first = runtime.active_for_conversation(goal.conversation_id)
        assert first is not None
        await runner.entered.wait()
        claim = store.get(goal.id).claim
        choose(store, goal, claim.id, action="continue")
        await scheduler.tick()
        assert len(runner.requests) == 1
        runner.release.set()
        await first.wait()
        await scheduler.tick()
        second = runtime.active_for_conversation(goal.conversation_id)
        assert second is not None
        await second.wait()
        assert len(runner.requests) == 2
        assert runner.requests[1].goal_trigger.wake_id != goal.next.id
    finally:
        runner.release.set()
        await runtime.close()


async def test_shutdown_leaves_claim_for_recovery_to_rerun_the_wake(store: GoalStore) -> None:
    goal = create(store, "goal-chat")
    runner = GoalRunner()
    runner.release.clear()
    runtime = AgentRuntime(runner, goal_store=store, shutdown_timeout=0.01)
    await make_scheduler(store, runtime).tick()
    await runner.entered.wait()
    await runtime.close()
    assert store.get(goal.id).claim is not None
    restarted = GoalStore(store._base)
    recovered = restarted.recover_claims()
    assert len(recovered) == 1
    assert recovered[0].next.id == goal.next.id
    assert recovered[0].next.reason == "interrupted"
    assert restarted.recover_claims() == []
    assert [item.id for item in restarted.due()] == [goal.id]


async def test_recover_then_run_tells_the_agent_it_was_interrupted(store: GoalStore) -> None:
    goal = create(store, "goal-chat")
    claimed = store.claim(goal.id, goal.next.id, "lost")
    assert claimed is not None
    runner = GoalRunner()
    runtime = AgentRuntime(runner, goal_store=store)
    try:
        GoalWorkSource(store, runtime, enabled=lambda: True).recover()
        await make_scheduler(store, runtime).tick()
        await runtime.active_for_conversation(goal.conversation_id).wait()
        assert runner.requests[0].goal_trigger.reason == "interrupted"
    finally:
        await runtime.close()


async def test_failed_run_sets_error_and_is_not_retried_by_itself(store: GoalStore) -> None:
    goal = create(store, "goal-chat")
    runner = GoalRunner()
    runner.result = ExecutionResult("error", error="Provider unavailable")
    runtime = AgentRuntime(runner, goal_store=store)
    scheduler = make_scheduler(store, runtime)
    try:
        await scheduler.tick()
        handle = runtime.active_for_conversation(goal.conversation_id)
        assert handle is not None
        await handle.wait()
        await scheduler.tick(datetime.now(timezone.utc) + timedelta(days=30))
        current = store.get(goal.id)
        assert current.next.kind == "error"
        assert current.next.message == "Provider unavailable"
        assert len(runner.requests) == 1
    finally:
        await runtime.close()


async def test_retry_runs_again_with_the_retry_reason(store: GoalStore) -> None:
    goal = failed(store, create(store, "goal-chat"))
    store.run(goal.id)
    runner = GoalRunner()
    runtime = AgentRuntime(runner, goal_store=store)
    try:
        await make_scheduler(store, runtime).tick()
        await runtime.active_for_conversation(goal.conversation_id).wait()
        assert runner.requests[0].goal_trigger.reason == "retry"
    finally:
        await runtime.close()


async def test_admission_conflict_releases_the_same_wake(store, monkeypatch):
    from agent_runtime import RunConflictError

    goal = create(store, "goal-chat")
    runtime = AgentRuntime(GoalRunner(), goal_store=store)

    async def conflict(_request):
        raise RunConflictError("The user started a turn")

    monkeypatch.setattr(runtime, "start", conflict)
    try:
        await make_scheduler(store, runtime).tick()
        current = store.get(goal.id)
        assert current.next == goal.next
        assert current.claim is None
        assert current.revision == goal.revision
    finally:
        await runtime.close()


async def test_admission_failure_sets_error(store, monkeypatch):
    goal = create(store, "goal-chat")
    runtime = AgentRuntime(GoalRunner(), goal_store=store)

    async def broken(_request):
        raise RuntimeError("No model configured")

    monkeypatch.setattr(runtime, "start", broken)
    try:
        await make_scheduler(store, runtime).tick()
        current = store.get(goal.id)
        assert current.next.kind == "error" and current.next.message == "No model configured"
        assert current.claim is None
    finally:
        await runtime.close()
