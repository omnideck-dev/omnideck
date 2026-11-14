"""Stop and turning Goals off end runs without changing what the goal does next."""

from __future__ import annotations

import asyncio

import pytest
from aiohttp import web

from agent_core.turn import ExecutionResult
from agent_runtime import AgentRunRequest, AgentRuntime, RunSession
from goals import GoalStore
from goals._scheduling import GoalWorkSource
from scheduling import Scheduler
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
    store = GoalStore(tmp_path / "session-goals")
    runner = StoppableRunner()
    runtime = AgentRuntime(runner, goal_store=store, goals_enabled=goals_enabled)
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


async def test_disable_goals_keeps_goal_state(app_client):
    client, store, _runtime, _runner = app_client
    later = scheduled(store, create(store, "later"))
    asking = waiting(store, create(store, "asking"))
    response = await client.put("/api/settings", json={"goals_enabled": False})
    assert response.status == 200
    assert store.get(later.id) == later
    assert store.get(asking.id) == asking
    assert (await client.put("/api/settings", json={"goals_enabled": True})).status == 200
    assert store.get(later.id) == later
    assert store.get(asking.id) == asking


async def test_disable_marks_wake_run_interrupted(app_client):
    client, store, runtime, runner = app_client
    goal = create(store)
    scheduler = Scheduler(max_concurrent=2, poll_interval=0.01, shutdown_timeout=0)
    scheduler.register(GoalWorkSource(store, runtime, enabled=goals_enabled))
    await scheduler.tick()
    await runner.entered.wait()
    handle = runtime.active_for_conversation(goal.conversation_id)
    assert store.get(goal.id).claim.wake_id == goal.next.id
    response = await client.put("/api/settings", json={"goals_enabled": False})
    assert response.status == 200
    assert (await handle.wait()).status == "stopped"
    current = store.get(goal.id)
    assert current.claim is None
    assert current.next.id == goal.next.id and current.next.reason == "interrupted"
    assert current.paused is False
    assert (await client.put("/api/settings", json={"goals_enabled": True})).status == 200
    assert [item.id for item in store.due()] == [goal.id]


async def test_disable_leaves_chat_turn_goal_unchanged(app_client):
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
