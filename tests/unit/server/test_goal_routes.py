"""Goal HTTP behavior, including experiment gating and conversation lifecycle."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from aiohttp import web

from agents import AgentProfile
from conversations import ConversationStore, conversation_exists, list_conversations
from goals import GoalStore
from server._agent_runtime import AGENT_RUNTIME_KEY
from server._agent_run_routes import register_agent_run_routes
from server._conversation_routes import register_conversation_routes
from server._goal_routes import register_goal_routes
from server._goals import GOAL_STORE_KEY
from server._settings_routes import register_settings_routes
from server.aiohttp_app import cors_and_error_middleware

BASE = "/api/conversations/sessions/chat-1/goal"
HEADERS = {"X-Requested-With": "XMLHttpRequest"}


@pytest.fixture
async def goal_client(tmp_path, monkeypatch, aiohttp_client):
    enabled = {"value": True}
    monkeypatch.setattr("server._goal_routes.goals_enabled", lambda: enabled["value"])
    monkeypatch.setattr("settings._settings_path", lambda: tmp_path / "settings.json")
    profile = AgentProfile(id="test", name="Test", provider="fake", model="fake")
    monkeypatch.setattr("server._goal_routes.get_agent_profile", lambda _id: profile)
    monkeypatch.setattr("server._goal_routes.get_default_profile", lambda: profile)
    store = GoalStore(tmp_path / "session-goals")
    runtime = MagicMock()
    runtime.active_for_conversation.return_value = None
    runtime.conversations = ConversationStore()
    app = web.Application(middlewares=[cors_and_error_middleware])
    app[GOAL_STORE_KEY] = store
    app[AGENT_RUNTIME_KEY] = runtime
    register_goal_routes(app)
    register_conversation_routes(app)
    register_agent_run_routes(app)
    register_settings_routes(app)
    client = await aiohttp_client(app, headers=HEADERS)
    yield client, store, runtime, enabled
    await runtime.conversations.close()


async def assign(client, **fields):
    return await client.post(BASE, json={"objective": "Find a dentist and book an appointment", **fields})


async def test_assign_to_empty_chat_persists_chat_and_initial_wake(goal_client):
    client, store, _, _ = goal_client
    response = await assign(client, kind="ongoing")
    assert response.status == 201
    goal = (await response.json())["goal"]
    assert goal["conversation_id"] == "chat-1"
    assert goal["kind"] == "ongoing"
    assert "constraints" not in goal and "success_criteria" not in goal
    assert not goal["running"]
    assert store.due()[0].id == goal["id"]
    assert conversation_exists("chat-1")
    assert list_conversations()[0].title == "Find a dentist and book an appointment"
    assert (await (await client.get("/api/goals")).json())["goals"][0]["id"] == goal["id"]


async def test_only_one_unfinished_goal_and_terminal_history_survives(goal_client):
    client, store, _, _ = goal_client
    assert (await assign(client)).status == 201
    assert (await assign(client)).status == 409
    old = store.current("chat-1")
    store.complete(old.id, "Appointment confirmed for Tuesday")
    assert (await assign(client, objective="Plan household meals")).status == 201
    body = await (await client.get(BASE)).json()
    assert body["goal"]["objective"] == "Plan household meals"
    assert len(body["history"]) == 1
    assert body["history"][0]["outcome"] == "Appointment confirmed for Tuesday"


async def test_user_plan_edit_conflicts_instead_of_losing_agent_progress(goal_client):
    client, store, _, _ = goal_client
    await assign(client)
    goal = store.current("chat-1")
    store.record_progress(goal.id, "Found three candidates")
    response = await client.patch(BASE, json={
        "expected_revision": goal.revision,
        "plan": [{"id": "call", "title": "Contact candidates"}],
    })
    assert response.status == 409
    assert store.current("chat-1").progress[0].summary == "Found three candidates"
    latest = store.current("chat-1")
    response = await client.patch(BASE, json={
        "expected_revision": latest.revision,
        "plan": [{"id": "call", "title": "Contact candidates"}],
    })
    assert response.status == 200
    assert store.current("chat-1").plan[0].id == "call"


async def test_patch_requires_same_origin_header(goal_client):
    client, store, _, _ = goal_client
    await assign(client)
    response = await client.patch(BASE, headers={"X-Requested-With": ""}, json={
        "expected_revision": store.current("chat-1").revision, "objective": "Changed",
    })
    assert response.status == 403


async def test_pause_revokes_wake_before_stopping_active_run(goal_client):
    client, store, runtime, _ = goal_client
    await assign(client)
    handle = MagicMock()
    handle.run_id = "run-1"
    runtime.active_for_conversation.return_value = handle
    handle.stop.side_effect = lambda: _assert_paused(store)
    response = await client.post(BASE + "/pause", json={})
    assert response.status == 200
    handle.stop.assert_called_once()
    runtime.active_for_conversation.return_value = None
    assert (await client.post(BASE + "/resume", json={})).status == 200
    assert len(store.due()) == 1


def _assert_paused(store):
    assert store.current("chat-1").status == "paused"
    assert store.due() == []


async def test_chat_stop_also_pauses_goal(goal_client):
    client, store, _, _ = goal_client
    await assign(client)
    response = await client.post("/api/chat/stop?conversation_id=chat-1")
    assert response.status == 200
    _assert_paused(store)


async def test_archive_pauses_and_restore_does_not_restart_goal(goal_client):
    client, store, _, _ = goal_client
    await assign(client)
    assert (await client.post("/api/conversations/sessions/chat-1/archive")).status == 204
    _assert_paused(store)
    assert (await (await client.get("/api/goals")).json())["goals"] == []
    assert (await client.post(BASE + "/resume", json={})).status == 409
    assert (await assign(client)).status == 409
    assert (await client.post("/api/conversations/sessions/chat-1/unarchive")).status == 204
    _assert_paused(store)


async def test_delete_removes_goal_and_wake(goal_client):
    client, store, _, _ = goal_client
    await assign(client)
    assert (await client.delete("/api/conversations/sessions/chat-1")).status == 204
    assert store.list() == []


async def test_goals_api_is_unavailable_when_experiment_disabled(goal_client):
    client, store, _, enabled = goal_client
    enabled["value"] = False
    for method, path in [("get", BASE), ("get", "/api/goals"), ("post", BASE), ("patch", BASE)]:
        response = await getattr(client, method)(path, json={"objective": "A goal"})
        assert response.status == 404
    assert store.list() == []


async def test_disabling_experiment_pauses_and_stops_without_deleting_progress(goal_client):
    client, store, runtime, _ = goal_client
    await assign(client)
    goal = store.current("chat-1")
    store.record_progress(goal.id, "Insurance details gathered")
    handle = MagicMock()
    runtime.active_for_conversation.return_value = handle
    handle.stop.side_effect = lambda: _assert_paused(store)
    response = await client.put("/api/settings", json={"goals_enabled": False})
    assert response.status == 200
    assert (await response.json())["goals_enabled"] is False
    handle.stop.assert_called_once()
    assert store.current("chat-1").progress[0].summary == "Insurance details gathered"
    assert (await client.put("/api/settings", json={"goals_enabled": True})).status == 200
    _assert_paused(store)


async def test_invalid_assignment_does_not_create_conversation_or_wake(goal_client):
    client, store, _, _ = goal_client
    response = await assign(client, objective="   ")
    assert response.status == 400
    assert not conversation_exists("chat-1")
    assert store.list() == []


async def test_unrelated_chat_run_does_not_mark_paused_goal_running(goal_client):
    client, store, runtime, _ = goal_client
    await assign(client)
    store.pause(store.current("chat-1").id)
    handle = MagicMock()
    handle.run_id = "unrelated-turn"
    runtime.active_for_conversation.return_value = handle
    body = await (await client.get(BASE)).json()
    assert body["goal"]["status"] == "paused"
    assert body["goal"]["running"] is False
    assert body["goal"]["run_id"] is None


@pytest.mark.parametrize("action", ["archive", "delete"])
async def test_conversation_removal_disarms_wake_before_files_change(goal_client, monkeypatch, action):
    client, store, _, _ = goal_client
    await assign(client)
    from server import _conversation_routes

    original = getattr(_conversation_routes, f"{action}_conversation")

    def checked_remove(conversation_id):
        assert store.due() == []
        assert store.latest(conversation_id).status in {"paused", "cancelled"}
        return original(conversation_id)

    monkeypatch.setattr(_conversation_routes, f"{action}_conversation", checked_remove)
    if action == "archive":
        response = await client.post("/api/conversations/sessions/chat-1/archive")
    else:
        response = await client.delete("/api/conversations/sessions/chat-1")
    assert response.status == 204


async def test_pause_by_goal_identity_wins_over_new_progress(goal_client):
    client, store, _, _ = goal_client
    await assign(client)
    seen_goal = store.current("chat-1")
    store.record_progress(seen_goal.id, "More progress since the UI refreshed")
    response = await client.post(BASE + "/pause", json={"goal_id": seen_goal.id})
    assert response.status == 200
    _assert_paused(store)


async def test_old_control_cannot_pause_a_replacement_goal(goal_client):
    client, store, _, _ = goal_client
    await assign(client)
    old = store.current("chat-1")
    store.complete(old.id, "Appointment confirmed")
    await assign(client, objective="Organize household tasks")
    response = await client.post(BASE + "/pause", json={"goal_id": old.id})
    assert response.status == 409
    assert store.current("chat-1").status == "active"


@pytest.mark.parametrize("operation", ["assign", "resume"])
async def test_disable_wins_over_goal_mutation_waiting_for_body(goal_client, monkeypatch, operation):
    from settings import goals_enabled, save_settings

    client, store, _runtime, _enabled = goal_client
    if operation == "resume":
        await assign(client)
        store.pause(store.current("chat-1").id)
    save_settings({"goals_enabled": True})
    monkeypatch.setattr("server._goal_routes.goals_enabled", goals_enabled)
    path = BASE if operation == "assign" else BASE + "/resume"
    entered = asyncio.Event()
    release = asyncio.Event()
    original_text = web.Request.text

    async def delayed_text(request):
        if request.path == path:
            entered.set()
            await release.wait()
        return await original_text(request)

    monkeypatch.setattr(web.Request, "text", delayed_text)

    async def request_mutation():
        body = {"objective": "Plan the household schedule"} if operation == "assign" else {}
        return await client.post(path, json=body)

    pending = asyncio.create_task(request_mutation())
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        disabled = await client.put("/api/settings", json={"goals_enabled": False})
        assert disabled.status == 200
        release.set()
        response = await asyncio.wait_for(pending, timeout=1)
        assert response.status == 404
        assert store.due() == []
        if operation == "assign":
            assert store.list() == []
            assert not conversation_exists("chat-1")
        else:
            assert store.current("chat-1").status == "paused"
        assert (await client.put("/api/settings", json={"goals_enabled": True})).status == 200
        assert store.due() == []
    finally:
        release.set()
        await pending


async def test_history_is_lazy_searchable_paged_and_scoped_to_its_conversation(goal_client):
    client, store, _, enabled = goal_client
    await assign(client)
    goal = store.current('chat-1')
    for index in range(60):
        store.record_progress(goal.id, f'Progress {index}')
    snapshot = await (await client.get(BASE)).json()
    assert len(snapshot['goal']['progress']) == 20
    assert snapshot['goal']['progress_count'] == 60
    assert snapshot['history'] == []
    url = BASE + '/history'
    first = await (await client.get(url, params={'goal_id': goal.id, 'q': 'Progress'})).json()
    second = await (await client.get(url, params={'goal_id': goal.id, 'q': 'Progress', 'before': first['next_before']})).json()
    assert len(first['entries']) == len(second['entries']) == 20
    assert not {e['id'] for e in first['entries']} & {e['id'] for e in second['entries']}
    match = await (await client.get(url, params={'goal_id': goal.id, 'q': 'Progress 0'})).json()
    assert match['entries'][0]['summary'] == 'Progress 0'
    other = store.create('other-chat', 'Private goal', 'assistant')
    assert (await client.get(url, params={'goal_id': other.id})).status == 404
    assert (await client.get(url, params={'goal_id': goal.id, 'before': '-1'})).status == 400
    enabled['value'] = False
    assert (await client.get(url, params={'goal_id': goal.id})).status == 404


@pytest.mark.parametrize("field,value", [("constraints", "Mornings only"), ("success_criteria", ["Booked"])])
async def test_removed_goal_fields_are_rejected_by_assignment_and_edit(goal_client, field, value):
    client, store, _, _ = goal_client
    response = await assign(client, **{field: value})
    assert response.status == 400
    assert not store.list()
    goal = (await (await assign(client)).json())["goal"]
    response = await client.patch(BASE, json={"expected_revision": goal["revision"], field: value})
    assert response.status == 400
