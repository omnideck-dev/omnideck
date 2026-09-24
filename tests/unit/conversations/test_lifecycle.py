"""Conversation scopes own cleanup independently of concrete resource services."""

from unittest.mock import AsyncMock

import pytest

from conversations import ConversationStore


async def test_resources_close_once_when_conversation_is_evicted():
    store = ConversationStore()
    cleanup = AsyncMock()
    async with store.acquire("conversation") as scope:
        scope.resources.push_async_callback(cleanup)
    cleanup.assert_not_awaited()
    assert await store.evict_conversation("conversation")
    assert not await store.evict_conversation("conversation")
    await store.close()
    cleanup.assert_awaited_once()


async def test_failing_cleanup_is_reported_after_other_resources_close():
    store = ConversationStore()
    failing = AsyncMock(side_effect=RuntimeError("cleanup failed"))
    succeeding = AsyncMock()
    async with store.acquire("conversation") as scope:
        scope.resources.push_async_callback(succeeding)
        scope.resources.push_async_callback(failing)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        await store.evict_conversation("conversation")
    succeeding.assert_awaited_once()
    assert not await store.evict_conversation("conversation")


async def test_store_refuses_eviction_and_shutdown_while_conversation_is_leased():
    store = ConversationStore()
    async with store.acquire("conversation"):
        with pytest.raises(RuntimeError, match="leased"):
            await store.evict_conversation("conversation")
        with pytest.raises(RuntimeError, match="active leases"):
            await store.close()
    await store.close()
    with pytest.raises(RuntimeError, match="closed"):
        async with store.acquire("conversation"):
            pytest.fail("Closed store admitted a lease")


async def test_transient_conversation_waits_for_its_last_nested_lease():
    store = ConversationStore()
    cleanup = AsyncMock()
    async with store.acquire("conversation") as outer:
        async with store.acquire("conversation", transient=True) as inner:
            assert inner is outer
            inner.resources.push_async_callback(cleanup)
        cleanup.assert_not_awaited()
    cleanup.assert_awaited_once()
    assert not store._conversations and not store._leases


async def test_shutdown_cleans_other_conversations_even_when_one_cleanup_fails():
    store = ConversationStore()
    failing = AsyncMock(side_effect=RuntimeError("cleanup failed"))
    succeeding = AsyncMock()
    async with store.acquire("first") as scope:
        scope.resources.push_async_callback(succeeding)
    async with store.acquire("second") as scope:
        scope.resources.push_async_callback(failing)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        await store.close()
    failing.assert_awaited_once()
    succeeding.assert_awaited_once()
    assert not store._conversations


async def test_cancelled_owner_releases_lease_after_another_eviction_unlocks():
    import asyncio

    store = ConversationStore()
    blocked, release_eviction, acquired, finish = (asyncio.Event() for _ in range(4))
    cleanup = AsyncMock()

    async def slow_cleanup():
        blocked.set()
        await release_eviction.wait()

    async with store.acquire("other") as scope:
        scope.resources.push_async_callback(slow_cleanup)

    async def owner():
        async with store.acquire("transient", transient=True) as scope:
            scope.resources.push_async_callback(cleanup)
            acquired.set()
            await finish.wait()

    task = asyncio.create_task(owner())
    await acquired.wait()
    eviction = asyncio.create_task(store.evict_conversation("other"))
    await blocked.wait()
    finish.set()
    # Give the owner a chance to reach its lease release behind the locked store.
    await asyncio.sleep(0)
    task.cancel()
    release_eviction.set()
    await asyncio.wait_for(eviction, 5)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    cleanup.assert_awaited_once()
    assert not store._leases and not store._conversations
