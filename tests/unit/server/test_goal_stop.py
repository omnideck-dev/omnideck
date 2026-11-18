"""Stop and turning Goals off in settings end a goal chat turn without changing the goal."""

from __future__ import annotations

import asyncio

import pytest
from aiohttp import web

from agent_core.turn import ExecutionResult
from agent_runtime import AgentRunRequest, AgentRuntime, RunSession
from goals import GoalRunExtension, GoalStore
from server._agent_runtime import AGENT_RUNTIME_KEY
from server._agent_run_routes import register_agent_run_routes
from server._goals import GOAL_STORE_KEY
from server._settings_routes import register_settings_routes
from server.aiohttp_app import cors_and_error_middleware
from settings import goals_enabled, save_settings

from tests.unit.goals.support import create, scheduled, waiting

HEADERS = {"X-Requested-With": "XMLHttpRequest"}


class StoppableRunner:
    """Runs until the run is asked to stop."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()

    async def run(self, request: AgentRunRequest, session: RunSession) -> ExecutionResult:
        self.entered.set()
        await session.stop_event.wait()
        return ExecutionResult("stopped")


@pytest.fixture
async def app_client(tmp_path, monkeypatch, aiohttp_client):
    monkeypatch.setattr("settings._settings_path", lambda: tmp_path / "settings.json")
    save_settings({"goals_enabled": True})
    store = GoalStore(tmp_path / "goals")
    runner = StoppableRunner()
    runtime = AgentRuntime(runner, extensions=[GoalRunExtension(store, enabled=goals_enabled)])
    app = web.Application(middlewares=[cors_and_error_middleware])
    app[GOAL_STORE_KEY] = store
    app[AGENT_RUNTIME_KEY] = runtime
    register_agent_run_routes(app)
    register_settings_routes(app)
    client = await aiohttp_client(app, headers=HEADERS)
    yield client, store, runtime, runner
    await runtime.close()


async def start_chat_turn(runtime, runner, conversation_id="chat"):
    handle = await runtime.start(AgentRunRequest(conversation_id, "How is it going?", None, "assistant"))
    await runner.entered.wait()
    return handle


async def test_stop_does_not_pause_goal(app_client):
    client, store, runtime, runner = app_client
    goal = scheduled(store, create(store))
    handle = await start_chat_turn(runtime, runner)
    assert store.get(goal.id).claim is not None
    response = await client.post("/api/chat/stop?conversation_id=chat")
    assert response.status == 200
    assert (await handle.wait()).status == "stopped"
    current = store.get(goal.id)
    assert current.paused is False
    assert current.next == goal.next
    assert current.claim is None
    assert current.revision == goal.revision


async def test_turning_goals_off_in_settings_stops_a_goal_chat_turn(app_client):
    client, store, runtime, runner = app_client
    goal = waiting(store, create(store))
    handle = await start_chat_turn(runtime, runner)
    assert store.get(goal.id).claim is not None
    response = await client.put("/api/settings", json={"goals_enabled": False})
    assert response.status == 200
    assert (await handle.wait()).status == "stopped"
    current = store.get(goal.id)
    assert current.claim is None
    assert current.next == goal.next
    assert current.revision == goal.revision
    assert current.paused is False
