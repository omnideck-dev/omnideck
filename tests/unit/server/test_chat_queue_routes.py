"""Sending while the agent works queues the message; the queue can be edited over HTTP."""

from __future__ import annotations

import asyncio

import pytest
from aiohttp import web

from agent_core.events import AgentEvent, UserMessagePayload
from agent_core.turn import ExecutionResult
from agent_runtime import AgentRuntime
from goals import GoalStore
from server._agent_run_routes import register_agent_run_routes
from server._agent_runtime import AGENT_RUNTIME_KEY
from server._goal_routes import register_goal_routes
from server._goals import GOAL_STORE_KEY, save_goal_answers_when_read
from server.aiohttp_app import cors_and_error_middleware

from tests.unit.goals.support import waiting

HEADERS = {"X-Requested-With": "XMLHttpRequest"}
CHAT = {"conversation_id": "chat-1", "profile_id": "assistant", "message": "start"}
ANSWERS = "/api/conversations/sessions/chat-1/goal/answers"


class WorkingRunner:
    """Publishes the opening message, then works until released."""

    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run(self, request, session):
        session.add_event(AgentEvent(payload=UserMessagePayload(
            type="user_message", content=request.message, context=list(request.context),
        )))
        self.started.set()
        await self.release.wait()
        return ExecutionResult("success")


@pytest.fixture
async def queue_client(tmp_path, monkeypatch, aiohttp_client):
    enabled = {"value": True}
    monkeypatch.setattr("server._goal_routes.goals_enabled", lambda: enabled["value"])
    monkeypatch.setattr("server._goals.goals_enabled", lambda: enabled["value"])
    store = GoalStore(tmp_path / "goals")
    runner = WorkingRunner()
    runtime = AgentRuntime(runner, goal_store=store)
    app = web.Application(middlewares=[cors_and_error_middleware])
    app[GOAL_STORE_KEY] = store
    app[AGENT_RUNTIME_KEY] = runtime
    save_goal_answers_when_read(app)
    register_agent_run_routes(app)
    register_goal_routes(app)
    client = await aiohttp_client(app, headers=HEADERS)
    try:
        yield client, runner, runtime, store, enabled
    finally:
        runner.release.set()
        await runtime.close()


async def start_run(client, runner):
    response = await client.post("/api/chat", json=CHAT)
    assert response.status == 200
    await runner.started.wait()
    return response


async def test_chat_while_the_agent_works_returns_202_with_the_queued_message(queue_client):
    client, runner, runtime, _, _ = queue_client
    stream = await start_run(client, runner)
    run_id = runtime.active_for_conversation("chat-1").run_id
    queued = await client.post("/api/chat", json={**CHAT, "message": "also this"})
    assert queued.status == 202
    body = await queued.json()
    assert body["nudge"]["run_id"] == run_id
    assert isinstance(body["nudge"]["id"], str) and body["nudge"]["id"]
    stream.close()


async def test_chat_with_files_while_the_agent_works_returns_409(queue_client):
    client, runner, _, _, _ = queue_client
    stream = await start_run(client, runner)
    response = await client.post("/api/chat", json={
        **CHAT, "message": "see file", "data": [{"base64": "aGk=", "content_type": "text/plain", "filename": "a.txt"}],
    })
    assert response.status == 409
    assert (await response.json())["error"] == "Files can be sent after the agent finishes."
    stream.close()


async def test_delete_nudge_removes_it_once_then_reports_it_was_read(queue_client):
    client, runner, runtime, _, _ = queue_client
    assert (await client.delete("/api/chat/nudges/missing?conversation_id=chat-1")).status == 404
    stream = await start_run(client, runner)
    nudge_id = (await (await client.post("/api/chat", json={**CHAT, "message": "oops"})).json())["nudge"]["id"]
    removed = await client.delete(f"/api/chat/nudges/{nudge_id}?conversation_id=chat-1")
    assert removed.status == 200 and await removed.json() == {"ok": True}
    again = await client.delete(f"/api/chat/nudges/{nudge_id}?conversation_id=chat-1")
    assert again.status == 409
    assert (await again.json())["error"] == "The agent already read this message."
    handle = runtime.active_for_conversation("chat-1")
    runner.release.set()
    await handle.wait()
    lines = (await stream.text()).splitlines()
    assert any('"nudge_removed"' in line and '"removed"' in line for line in lines)
    assert any('"nudge_queued"' in line for line in lines)


async def test_goal_answers_route_starts_a_run_and_saves_when_it_opens(queue_client):
    client, runner, _, store, _ = queue_client
    goal = waiting(store, store.create("chat-1", "Find a dentist", "assistant"), "insurance", "Which insurance plan?")
    body = {"goal_id": goal.id, "answers": [{"question_id": "insurance", "question_revision": 1, "answer": "Aetna"}]}
    response = await client.post(ANSWERS, json=body)
    assert response.status == 200
    await runner.started.wait()
    assert [answer.answer for answer in store.get(goal.id).questions[0].answers] == ["Aetna"]
    runner.release.set()
    text = await response.text()
    assert '"goal_question"' in text
    repeated = await client.post(ANSWERS, json=body)
    assert repeated.status == 409
    assert "already sent" in (await repeated.json())["error"]


async def test_goal_answers_route_queues_while_the_agent_works(queue_client):
    client, runner, _, store, _ = queue_client
    goal = waiting(store, store.create("chat-1", "Find a dentist", "assistant"), "insurance", "Which insurance plan?")
    stream = await start_run(client, runner)
    response = await client.post(ANSWERS, json={
        "goal_id": goal.id, "answers": [{"question_id": "insurance", "question_revision": 1, "answer": "Aetna"}],
    })
    assert response.status == 202
    assert "nudge" in await response.json()
    assert store.get(goal.id).questions[0].answers == []
    stream.close()


async def test_goal_answers_route_refuses_stale_versions_and_disabled_goals(queue_client):
    client, _, _, store, enabled = queue_client
    goal = waiting(store, store.create("chat-1", "Find a dentist", "assistant"), "insurance", "Which insurance plan?")
    body = {"goal_id": goal.id, "answers": [{"question_id": "insurance", "question_revision": 2, "answer": "Aetna"}]}
    stale = await client.post(ANSWERS, json=body)
    assert stale.status == 409
    enabled["value"] = False
    assert (await client.post(ANSWERS, json=body)).status == 404
