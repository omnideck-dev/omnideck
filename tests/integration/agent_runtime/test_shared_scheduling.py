"""Goals and routines use one scheduler with real disk stores and runtime."""
import asyncio
from datetime import datetime, timedelta, timezone

from goals import GoalStep, GoalStore
from goals._models import GoalChoice
from goals._scheduling import GoalWorkSource
from scheduling import Scheduler
from tasks import RoutineWorkSource, TaskExecutor

from ._support import reply


def make_scheduler(h, tmp_path, *, capacity=1):
    store = GoalStore(tmp_path / 'goals')
    h.manager._goal_store = store
    h.manager._runner.goal_store = store
    scheduler = Scheduler(max_concurrent=capacity, poll_interval=0.01, shutdown_timeout=0)
    scheduler.register(GoalWorkSource(store, h.manager, enabled=lambda: True))
    routines = RoutineWorkSource(h.store, TaskExecutor(h.store, h.manager), h.config.routines, scheduler=scheduler)
    scheduler.register(routines)
    return store, scheduler, routines


async def test_goals_and_routines_share_capacity_and_take_turns(harness, tmp_path):
    h = harness
    h.profile()
    store, scheduler, routines = make_scheduler(h, tmp_path)
    store.create('goal-1', 'First goal', 'leaf')
    store.create('goal-2', 'Second goal', 'leaf')
    routine = h.store.create_routine('Routine', auto_run=False)
    h.store.create_task(routine.id, 'Task', 'Run routine', agent_profile='leaf')
    run = h.store.queue_run(routine.id)
    entered, release = asyncio.Queue(), asyncio.Queue()

    async def hold(request):
        entered.put_nowait(request)
        await release.get()
        yield reply('Done')

    h.provider.plan('leaf', hold, hold, hold)
    try:
        await asyncio.gather(scheduler.tick(), scheduler.tick())
        await asyncio.wait_for(entered.get(), 3)
        assert len(scheduler.active('goals')) == 1
        assert not scheduler.active('routines')
        first = scheduler.active('goals')[0].completion
        release.put_nowait(True)
        await first
        await scheduler.tick()
        await asyncio.wait_for(entered.get(), 3)
        assert not scheduler.active('goals')
        assert len(scheduler.active('routines')) == 1
        routine_execution = scheduler.active('routines')[0].completion
        release.put_nowait(True)
        await routine_execution
        assert h.store.get_run(run.id).status == 'completed'
        await scheduler.tick()
        await asyncio.wait_for(entered.get(), 3)
        assert len(scheduler.active('goals')) == 1
        release.put_nowait(True)
        await scheduler.active('goals')[0].completion
        assert len(h.provider.requests) == 3
    finally:
        for _ in range(3):
            release.put_nowait(True)
        await scheduler.stop()


async def test_shared_start_recovers_interrupted_goal_and_routine_from_disk(harness, tmp_path):
    h = harness
    h.profile()
    store, scheduler, _ = make_scheduler(h, tmp_path, capacity=2)
    goal = store.create('interrupted', 'Check the prior action', 'leaf')
    store.claim(goal.id, goal.next.id, 'old-process')
    routine = h.store.create_routine('Interrupted routine', auto_run=False)
    h.store.create_task(routine.id, 'Task', 'Resume work', agent_profile='leaf')
    run = h.store.queue_run(routine.id)
    h.store.mark_task_result_running(h.store.get_task_results(run.id)[0].id)
    entered, release = asyncio.Queue(), asyncio.Event()

    async def hold(request):
        entered.put_nowait(request)
        await release.wait()
        yield reply('Recovered')

    h.provider.plan('leaf', hold, hold)
    try:
        await scheduler.start()
        await asyncio.wait_for(entered.get(), 3)
        await asyncio.wait_for(entered.get(), 3)
        assert len(scheduler.active('goals')) == len(scheduler.active('routines')) == 1
        assert store.get(goal.id).claim.id != 'old-process'
        assert store.get(goal.id).next.reason == 'interrupted'
        assert any('The last run was interrupted' in str(request['messages']) for request in h.provider.requests)
        release.set()
        await asyncio.gather(*(entry.completion for source in ('goals', 'routines') for entry in scheduler.active(source)))
        assert h.store.get_run(run.id).status == 'completed'
        assert len(h.provider.requests) == 2
    finally:
        release.set()
        await scheduler.stop()


async def test_recurring_routine_and_goal_use_same_explicit_clock(harness, tmp_path):
    h = harness
    h.profile()
    store, scheduler, _ = make_scheduler(h, tmp_path, capacity=2)
    future = datetime.now(timezone.utc) + timedelta(days=2)
    goal = store.create('future-goal', 'Review tomorrow', 'leaf')
    goal = store.update(goal.id, goal.revision, plan=[GoalStep(id='report', title='Read report', status='in_progress')])
    store.claim_for_turn(goal.id, 'setup')
    store.choose(goal.id, GoalChoice.model_validate({'action': 'schedule', 'at': future.isoformat(), 'note': 'Wait for report.'}),
                 claim_id='setup', expected_revision=goal.revision)
    store.finish_run(goal.id, 'setup', 'setup-run', 'success')
    routine = h.store.create_routine('Daily digest', cron='0 9 * * *', timezone='America/Chicago')
    h.store.create_task(routine.id, 'Digest', 'Review results', agent_profile='leaf')
    h.provider.plan('leaf', reply('Reviewed'), reply('Digest ready'))
    try:
        await scheduler.tick(future)
        admitted = [entry.completion for source in ('goals', 'routines') for entry in scheduler.active(source)]
        assert len(admitted) == 2
        await asyncio.gather(*admitted)
        assert len(h.store.get_routine_runs(routine.id)) == 1
        assert len(h.provider.requests) == 2
    finally:
        await scheduler.stop()


async def test_pausing_routine_source_does_not_pause_goal_work(harness, tmp_path):
    h = harness
    h.profile()
    store, scheduler, routines = make_scheduler(h, tmp_path)
    store.create('goal', 'Review report', 'leaf')
    routine = h.store.create_routine('Routine', auto_run=False)
    h.store.create_task(routine.id, 'Task', 'Do task', agent_profile='leaf')
    run = h.store.queue_run(routine.id)
    h.provider.plan('leaf', reply('Goal checked'), reply('Routine checked'))
    routines.pause()
    try:
        await scheduler.tick()
        await scheduler.active('goals')[0].completion
        assert h.store.get_run(run.id).status == 'pending'
        assert not scheduler.active('routines')
        routines.resume()
        await scheduler.tick()
        await scheduler.active('routines')[0].completion
        assert h.store.get_run(run.id).status == 'completed'
    finally:
        await scheduler.stop()


async def test_scheduler_shutdown_preserves_goal_claim_for_runtime_restart(harness, tmp_path):
    h = harness
    h.profile()
    store, scheduler, _ = make_scheduler(h, tmp_path)
    goal = store.create('interrupted-goal', 'Check prior action before repeating', 'leaf')
    entered = asyncio.Event()

    async def hold(_request):
        entered.set()
        await asyncio.Event().wait()
        yield reply('Unreachable')

    h.provider.plan('leaf', hold)
    await scheduler.tick()
    await asyncio.wait_for(entered.wait(), 3)
    await scheduler.stop()
    # Stopping scheduling must not finish/release a still-running goal.
    assert store.get(goal.id).claim is not None
    await h.manager.close()
    restored = GoalStore(tmp_path / 'goals')
    assert restored.get(goal.id).claim is not None
    assert len(restored.recover_claims()) == 1
    recovered = restored.get(goal.id)
    assert recovered.claim is None
    assert recovered.next.id == goal.next.id and recovered.next.reason == 'interrupted'
    assert [item.id for item in restored.due()] == [goal.id]
    assert restored.recover_claims() == []
