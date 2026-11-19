"""Routine routes that reach the shared scheduler."""

from unittest.mock import MagicMock

import pytest
from aiohttp import web

from server._scheduling import SCHEDULER_KEY
from server._task_routes import register_task_routes
from tasks._file_store import FileTaskStore

HEADERS = {"X-Requested-With": "XMLHttpRequest"}


@pytest.fixture
async def routes(tmp_path, monkeypatch, aiohttp_client):
    store = FileTaskStore(tmp_path / "routines")
    monkeypatch.setattr("server._task_routes.get_store", lambda: store)
    scheduler = MagicMock()
    scheduler.running = True
    source = MagicMock()
    source.enabled = True
    source.status = {"paused": False, "active_tasks": 1, "max_concurrent": 4, "running_routine_ids": ["r"]}
    app = web.Application()
    app[SCHEDULER_KEY] = scheduler
    app["routine_work_source"] = source
    register_task_routes(app)
    client = await aiohttp_client(app, headers=HEADERS)
    return client, store, scheduler, source


async def test_run_now_wakes_the_scheduler(routes):
    client, store, scheduler, _source = routes
    routine = store.create_routine("Morning digest", auto_run=False)
    response = await client.post(f"/api/routines/{routine.id}/trigger")
    assert response.status == 201
    scheduler.wake.assert_called_once_with()


@pytest.mark.parametrize("scheduler_running,source_enabled,expected", [
    (True, True, True), (False, True, False), (True, False, False),
])
async def test_runner_status_is_running_only_when_scheduler_and_source_are(
    routes, scheduler_running, source_enabled, expected,
):
    client, _store, scheduler, source = routes
    scheduler.running = scheduler_running
    source.enabled = source_enabled
    body = await (await client.get("/api/runner/status")).json()
    assert body["running"] is expected
    assert body["max_concurrent"] == 4 and body["active_tasks"] == 1
