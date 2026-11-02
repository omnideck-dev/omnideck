"""Discovery is polled once per app; readers hold immutable run snapshots."""

import asyncio
from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock

import pytest

from brokering.broker_client import IntegrationError
from integrations.connection_cache import IntegrationConnectionCache
from integrations.service import IntegrationService

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _record(*grants):
    return {"id": "work", "slug": "gmail", "state": "running", "operation_grants": list(grants)}


def _cache(*, interval=60, timeout=1):
    service = AsyncMock(spec=IntegrationService)
    service.list_connections.return_value = [_record("email.messages.search")]
    cache = IntegrationConnectionCache(service, poll_interval=interval, request_timeout=timeout)
    return cache, service


async def test_snapshots_are_immutable_and_reads_do_not_fetch():
    cache, service = _cache()
    cache.start()
    cache.start()  # idempotent; never starts a second poller
    try:
        await asyncio.wait_for(cache.wait_loaded(), 1)
        before = cache.snapshot()
        assert cache.available
        for _ in range(20):
            assert cache.snapshot() is before
        service.list_connections.assert_awaited_once_with()
        with pytest.raises(FrozenInstanceError):
            before[0].state = "broken"
        service.list_connections.return_value = [_record("email.messages.send")]
        assert await cache.refresh()
        assert before[0].operation_grants == frozenset({"email.messages.search"})
        assert cache.snapshot()[0].operation_grants == frozenset({"email.messages.send"})
    finally:
        await cache.close()


@pytest.mark.parametrize("failure", [IntegrationError("offline"), ValueError("bad response")])
async def test_failure_clears_snapshot_and_refresh_recovers(failure):
    cache, service = _cache()
    cache.start()
    try:
        await asyncio.wait_for(cache.wait_loaded(), 1)
        before = cache.snapshot()
        service.list_connections.side_effect = failure
        assert not await cache.refresh()
        assert not cache.available
        assert cache.snapshot() == ()
        assert before  # already-running agents retain their snapshot
        service.list_connections.side_effect = None
        service.list_connections.return_value = []
        assert await cache.refresh()
        assert cache.available and cache.snapshot() == ()
    finally:
        await cache.close()


async def test_timeout_cancels_actual_request_and_next_poll_recovers():
    cache, service = _cache(interval=.01, timeout=.02)
    cancelled = asyncio.Event()

    async def hang_then_recover(*_args):
        service.list_connections.side_effect = None
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    service.list_connections.side_effect = hang_then_recover
    cache.start()
    try:
        await asyncio.wait_for(cancelled.wait(), 1)
        await asyncio.wait_for(cache.wait_loaded(), 1)
        assert cache.available
        assert service.list_connections.await_count >= 2
    finally:
        await cache.close()


async def test_refresh_during_inflight_fetch_is_not_lost_and_waiters_coalesce():
    cache, service = _cache()
    entered, release = asyncio.Event(), asyncio.Event()

    async def initial(*_args):
        entered.set()
        await release.wait()
        service.list_connections.side_effect = None
        return []

    service.list_connections.side_effect = initial
    cache.start()
    try:
        await asyncio.wait_for(entered.wait(), 1)
        first = asyncio.create_task(cache.refresh())
        second = asyncio.create_task(cache.refresh())
        await asyncio.sleep(0)
        assert not first.done()
        release.set()
        assert await asyncio.wait_for(asyncio.gather(first, second), 1) == [True, True]
        assert service.list_connections.await_count == 2
        assert cache.snapshot()
    finally:
        release.set()
        await cache.close()


async def test_close_cancels_fetch_and_pending_refresh_and_can_repeat():
    cache, service = _cache()
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def hang(*_args):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    service.list_connections.side_effect = hang
    cache.start()
    await asyncio.wait_for(entered.wait(), 1)
    waiter = asyncio.create_task(cache.refresh())
    await asyncio.sleep(0)
    await cache.close()
    assert cancelled.is_set()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    await cache.close()
    assert not cache.available


async def test_cancelling_refresh_waiter_does_not_cancel_shared_poll():
    cache, service = _cache()
    entered, release = asyncio.Event(), asyncio.Event()
    cache.start()
    try:
        await asyncio.wait_for(cache.wait_loaded(), 1)

        async def delayed():
            entered.set()
            await release.wait()
            return []

        service.list_connections.side_effect = delayed
        first = asyncio.create_task(cache.refresh())
        second = asyncio.create_task(cache.refresh())
        await asyncio.wait_for(entered.wait(), 1)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not second.done()
        release.set()
        assert await asyncio.wait_for(second, 1)
        assert cache.available and cache.snapshot() == ()
    finally:
        release.set()
        await cache.close()


@pytest.mark.parametrize("record", [
    {"id": "work", "slug": "gmail"},
    {"id": "work", "slug": "gmail", "state": "running", "operation_grants": [1]},
    None,
])
async def test_malformed_records_fail_closed(record):
    cache, service = _cache()
    service.list_connections.return_value = [record]
    cache.start()
    try:
        assert not await cache.refresh()
        assert not cache.available and cache.snapshot() == ()
    finally:
        await cache.close()
