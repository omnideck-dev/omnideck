"""Shared scheduler capacity, timing, lifecycle and failure isolation."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from scheduling import ScheduledWork, Scheduler

NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)


class Source:
    enabled = True

    def __init__(self, name):
        self.name = name
        self.jobs = {}
        self.started = []
        self.recovered = 0

    def recover(self):
        self.recovered += 1

    def pending(self, now):
        return list(self.jobs.values())

    def add(self, key, due=NOW, target=None):
        async def dispatch():
            self.started.append(key)
            self.jobs.pop(key)
            return asyncio.get_running_loop().create_future()
        self.jobs[key] = ScheduledWork(key, target or key, due, {"item": key}, dispatch)


def scheduler(*sources, capacity=2):
    service = Scheduler(max_concurrent=capacity, poll_interval=0.01, shutdown_timeout=0)
    for source in sources:
        service.register(source)
    return service


async def test_shared_capacity_rotates_sources_and_serializes_overlapping_ticks():
    goals, routines = Source('goals'), Source('routines')
    for i in range(3):
        goals.add(f'g{i}')
        routines.add(f'r{i}')
    service = scheduler(goals, routines, capacity=1)
    try:
        await asyncio.gather(service.tick(NOW), service.tick(NOW))
        assert goals.started == ['g0'] and not routines.started
        service.active('goals')[0].completion.set_result(None)
        await service.tick(NOW)
        assert routines.started == ['r0'] and goals.started == ['g0']
        service.active('routines')[0].completion.set_result(None)
        await service.tick(NOW)
        assert goals.started == ['g0', 'g1']
    finally:
        await service.stop()


async def test_future_replacement_cancellation_disabled_and_busy_target_are_rechecked():
    source = Source('jobs')
    source.add('replaced', NOW + timedelta(days=1))
    service = scheduler(source)
    try:
        await service.tick(NOW)
        assert not source.started
        source.jobs.clear()  # Durable schedule was cancelled/replaced.
        source.add('new', target='chat')
        source.add('other', target='chat')
        source.enabled = False
        await service.tick(NOW)
        assert not source.started
        source.enabled = True
        await service.tick(NOW)
        assert source.started == ['new']
        service.active('jobs')[0].completion.set_result(None)
        await service.tick(NOW)
        assert source.started == ['new', 'other']
    finally:
        await service.stop()


async def test_source_failure_does_not_stop_other_sources():
    class Broken(Source):
        def pending(self, now):
            raise OSError('Unavailable storage')
    broken, healthy = Broken('broken'), Source('healthy')
    healthy.add('ready')
    service = scheduler(broken, healthy)
    try:
        await service.tick(NOW)
        assert healthy.started == ['ready']
    finally:
        await service.stop()


async def test_deletion_blocks_admission_and_shutdown_does_not_cancel_cleanup_twice():
    source = Source('jobs')
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def work():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()

    async def dispatch():
        return asyncio.create_task(work())

    source.jobs['a'] = ScheduledWork('a', 'chat', NOW, {'item': 'a'}, dispatch)
    service = scheduler(source)
    await service.tick(NOW)
    await entered.wait()

    async def delete():
        async with service.block('jobs', 'item', 'a'):
            assert service.blocked('jobs', {'item': 'a'})
            source.jobs.clear()

    deletion = asyncio.create_task(delete())
    await cleaning.wait()
    await service.tick(NOW)
    shutdown = asyncio.create_task(service.stop())
    await asyncio.sleep(0)
    assert not deletion.done() and not shutdown.done()
    release.set()
    await asyncio.gather(deletion, shutdown)
    assert not service.active('jobs')
    source.add('late')
    await service.tick(NOW)
    assert not source.started


async def test_start_recovers_sources_once_and_stop_cancels_remaining_work():
    source = Source('jobs')
    source.add('a')
    service = scheduler(source)
    await service.start()
    await service.start()
    await service.tick(NOW)
    completion = service.active('jobs')[0].completion
    await service.stop()
    assert source.recovered == 1 and completion.cancelled()
    assert not service.running
    with pytest.raises(RuntimeError):
        await service.start()
