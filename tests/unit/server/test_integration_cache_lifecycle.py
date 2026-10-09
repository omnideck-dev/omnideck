"""Integration discovery participates in readiness without blocking recovery."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from integrations.connection_cache import IntegrationConnectionCache
from integrations.service import IntegrationService
from server import aiohttp_app
from server._integration_cache import INTEGRATION_CACHE_KEY

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


async def test_successful_empty_snapshot_releases_readiness_and_cleanup_stops_polling():
    service = AsyncMock(spec=IntegrationService)
    service.list_connections.return_value = []
    cache = IntegrationConnectionCache(service, poll_interval=60)
    app = web.Application()
    app[INTEGRATION_CACHE_KEY] = cache
    await aiohttp_app._init_integrations_signal(app)
    await aiohttp_app._init_ready_signal(app)
    try:
        await asyncio.wait_for(app["ready"].wait(), 1)
        assert cache.available and cache.snapshot() == ()
    finally:
        await aiohttp_app._stop_integrations(app)
    assert app["_integrations_load"].done()
    assert app["_ready_watcher"].done()
    assert not cache.available


async def test_startup_deadline_releases_readiness_but_discovery_can_recover(monkeypatch):
    monkeypatch.setattr(aiohttp_app, "_INTEGRATIONS_LOAD_DEADLINE_SECONDS", .01)
    service = AsyncMock(spec=IntegrationService)
    service.list_connections.side_effect = OSError("not ready")
    cache = IntegrationConnectionCache(service, poll_interval=.01)
    app = web.Application()
    app[INTEGRATION_CACHE_KEY] = cache
    await aiohttp_app._init_integrations_signal(app)
    await aiohttp_app._init_ready_signal(app)
    try:
        await asyncio.wait_for(app["ready"].wait(), 1)
        assert not cache.available
        service.list_connections.side_effect = None
        service.list_connections.return_value = []
        await asyncio.wait_for(cache.wait_loaded(), 1)
        assert cache.available
        assert app["ready"].is_set()
    finally:
        await aiohttp_app._stop_integrations(app)


async def test_shutdown_cancels_pending_startup_and_supervisor_request():
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def hang():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    service = AsyncMock(spec=IntegrationService)
    service.list_connections.side_effect = hang
    app = web.Application()
    app[INTEGRATION_CACHE_KEY] = IntegrationConnectionCache(service)
    await aiohttp_app._init_integrations_signal(app)
    await aiohttp_app._init_ready_signal(app)
    await asyncio.wait_for(entered.wait(), 1)
    await asyncio.wait_for(aiohttp_app._stop_integrations(app), 1)
    assert cancelled.is_set()
    assert app["_integrations_load"].done()
    assert app["_ready_watcher"].done()
