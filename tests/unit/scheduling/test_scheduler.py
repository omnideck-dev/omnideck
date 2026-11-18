"""Per-source run limits, timing, lifecycle and failure isolation in the shared scheduler."""
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
        self.jobs[key] = ScheduledWork(key, target or key, due, dispatch)


def scheduler(*sources, capacity=2):
    service = Scheduler(limits={source.name: capacity for source in sources}, poll_interval=0.01, shutdown_timeout=0)
    for source in sources:
        service.register(source)
    return service


async def test_source_at_its_limit_leaves_the_other_source_admitted():
    goals, routines = Source('goals'), Source('routines')
    for i in range(3):
        goals.add(f'g{i}')
        routines.add(f'r{i}')
    service = scheduler(goals, routines, capacity=1)
    try:
        await service.tick(NOW)
        assert goals.started == ['g0'] and routines.started == ['r0']
        service.active('routines')[0].completion.set_result(None)
        await service.tick(NOW)
        assert goals.started == ['g0'] and routines.started == ['r0', 'r1']
    finally:
        await service.stop()


async def test_overlapping_ticks_are_serialized():
    source = Source('jobs')
    for i in range(3):
        source.add(f'j{i}')
    service = scheduler(source, capacity=1)
    try:
        await asyncio.gather(service.tick(NOW), service.tick(NOW))
        assert source.started == ['j0']
    finally:
        await service.stop()


def test_register_refuses_a_source_without_a_limit():
    service = Scheduler(limits={'goals': 1}, poll_interval=0.01, shutdown_timeout=0)
    with pytest.raises(ValueError, match='no run limit'):
        service.register(Source('routines'))


async def test_future_replacement_cancellation_disabled_and_busy_target_are_rechecked():
    source = Source('jobs')
    source.add('replaced', NOW + timedelta(days=1))
    service = scheduler(source)
    try:
        await service.tick(NOW)
        assert not source.started
        source.jobs.clear()
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


async def test_start_recovers_other_sources_when_one_recover_fails():
    class Broken(Source):
        def recover(self):
            raise OSError('Unreadable goal file')
    broken, healthy = Broken('broken'), Source('healthy')
    healthy.add('ready')
    service = scheduler(broken, healthy)
    await service.start()
    try:
        assert healthy.recovered == 1
        assert service.running
        await service.tick(NOW)
        assert healthy.started == ['ready']
    finally:
        await service.stop()


async def test_shutdown_does_not_cancel_cleanup_twice():
    source = Source('jobs')
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    finished = []

    async def work():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
            finished.append(True)

    tasks = []

    async def dispatch():
        tasks.append(asyncio.create_task(work()))
        return tasks[-1]

    source.jobs['a'] = ScheduledWork('a', 'chat', NOW, dispatch)
    service = scheduler(source)
    await service.tick(NOW)
    await entered.wait()
    tasks[0].cancel()
    await cleaning.wait()
    shutdown = asyncio.create_task(service.stop())
    await asyncio.sleep(0)
    assert not shutdown.done()
    release.set()
    await shutdown
    assert finished == [True]


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
