"""Goal HTTP behavior, including experiment gating and conversation lifecycle."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from agents import AgentProfile
from conversations import ConversationStore, conversation_exists, list_conversations
from goals import GoalStep, GoalStore
from server._agent_runtime import AGENT_RUNTIME_KEY
from server._agent_run_routes import register_agent_run_routes
from server._conversation_routes import register_conversation_routes
from server._goal_routes import register_goal_routes
from server._goals import GOAL_STORE_KEY
from server._settings_routes import register_settings_routes
from server.aiohttp_app import cors_and_error_middleware

from tests.unit.goals.support import claim_wake, completed, failed, scheduled, with_plan

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
    runtime.start = AsyncMock()
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


def running(runtime, run_id="run-1"):
    handle = MagicMock()
    handle.run_id = run_id
    runtime.active_for_conversation.return_value = handle
    return handle


async def test_assign_to_empty_chat_persists_chat_and_initial_wake(goal_client):
    client, store, _, _ = goal_client
    response = await assign(client)
    assert response.status == 201
    goal = (await response.json())["goal"]
    assert goal["conversation_id"] == "chat-1"
    assert "kind" not in goal and "status" not in goal
    assert goal["next"]["kind"] == "wake" and goal["next"]["reason"] == "planned"
    assert goal["paused"] is False and goal["claim"] is None
    assert goal["next_step"] is None
    assert not goal["running"]
    assert store.due()[0].id == goal["id"]
    assert conversation_exists("chat-1")
    assert list_conversations()[0].title == "Find a dentist and book an appointment"
    assert (await (await client.get("/api/goals")).json())["goals"][0]["id"] == goal["id"]


async def test_goal_view_names_the_step_the_next_run_works_on(goal_client):
    client, store, _, _ = goal_client
    await assign(client)
    with_plan(store, store.current("chat-1"),
              GoalStep(id="find", title="Find three dentists", status="done"),
              GoalStep(id="call", title="Call the first dentist", depends_on=["find"]))
    goal = (await (await client.get(BASE)).json())["goal"]
    assert goal["next_step"] == "Call the first dentist"


async def test_only_one_unfinished_goal_and_ended_history_survives(goal_client):
    client, store, _, _ = goal_client
    assert (await assign(client)).status == 201
    assert (await assign(client)).status == 409
    completed(store, store.current("chat-1"), "Appointment confirmed for Tuesday")
    assert (await assign(client, objective="Plan household meals")).status == 201
    body = await (await client.get(BASE)).json()
    assert body["goal"]["objective"] == "Plan household meals"
    assert len(body["history"]) == 1
    assert body["history"][0]["next"] == {"kind": "done", "outcome": "Appointment confirmed for Tuesday"}


async def test_user_plan_edit_conflicts_instead_of_losing_agent_progress(goal_client):
    client, store, _, _ = goal_client
    await assign(client)
    goal = store.current("chat-1")
    store.update(goal.id, goal.revision, summary="Found three candidates")
    response = await client.patch(BASE, json={
        "expected_revision": goal.revision,
        "plan": [{"id": "call", "title": "Contact candidates"}],
    })
    assert response.status == 409
    assert store.current("chat-1").summary == "Found three candidates"
    latest = store.current("chat-1")
    response = await client.patch(BASE, json={
        "expected_revision": latest.revision,
        "plan": [{"id": "call", "title": "Contact candidates"}],
    })
    assert response.status == 200
    assert store.current("chat-1").plan[0].id == "call"


async def test_user_plan_edit_keeps_step_progress_as_the_agent_saved_it(goal_client):
    client, store, _, _ = goal_client
    await assign(client)
    goal = with_plan(store, store.current("chat-1"),
                     GoalStep(id="find", title="Find three dentists", status="done"))
    response = await client.patch(BASE, json={
        "expected_revision": goal.revision,
        "plan": [{"id": "find", "title": "Find three dentists near work", "status": "pending"},
                 {"id": "call", "title": "Call them", "status": "done"}],
    })
    assert response.status == 200
    plan = store.current("chat-1").plan
    assert [(step.title, step.status) for step in plan] == [
        ("Find three dentists near work", "done"), ("Call them", "pending"),
    ]


async def test_route_edit_records_user_actor(goal_client):
    client, store, _, _ = goal_client
    await assign(client)
    goal = store.current("chat-1")
    response = await client.patch(BASE, json={"expected_revision": goal.revision, "objective": "Find a dentist"})
    assert response.status == 200
    entry = store.read_history(goal.id)["entries"][0]
    assert entry["summary"] == "Changed the objective."
    assert entry["actor"] == "user" and entry["claim_id"] is None


async def test_patch_requires_same_origin_header(goal_client):
    client, store, _, _ = goal_client
    await assign(client)
    response = await client.patch(BASE, headers={"X-Requested-With": ""}, json={
        "expected_revision": store.current("chat-1").revision, "objective": "Changed",
    })
    assert response.status == 403


async def test_pause_saves_before_stopping_active_run_and_resume_keeps_the_wake(goal_client):
    client, store, runtime, _ = goal_client
    await assign(client)
    handle = running(runtime)
    handle.stop.side_effect = lambda: _assert_paused(store)
    response = await client.post(BASE + "/pause", json={})
    assert response.status == 200
    handle.stop.assert_called_once()
    runtime.active_for_conversation.return_value = None
    response = await client.post(BASE + "/resume", json={})
    assert response.status == 200
    assert (await response.json())["goal"]["paused"] is False
    assert len(store.due()) == 1


def _assert_paused(store):
    assert store.current("chat-1").paused
    assert store.due() == []


async def test_pause_during_wake_run_marks_the_wake_interrupted(goal_client):
    client, store, runtime, _ = goal_client
    await assign(client)
    goal = claim_wake(store, store.current("chat-1"))
    running(runtime)
    assert (await client.post(BASE + "/pause", json={})).status == 200
    current = store.current("chat-1")
    assert current.claim is None
    assert current.next.id == goal.next.id and current.next.reason == "interrupted"


async def test_stop_route_does_not_pause_goal(goal_client):
    client, store, runtime, _ = goal_client
    await assign(client)
    goal = scheduled(store, store.current("chat-1"))
    handle = running(runtime)
    response = await client.post("/api/chat/stop?conversation_id=chat-1")
    assert response.status == 200
    handle.stop.assert_called_once()
    current = store.current("chat-1")
    assert current.paused is False
    assert current.next == goal.next
    assert current.revision == goal.revision


async def test_archive_pauses_and_restore_does_not_restart_goal(goal_client):
    client, store, _, _ = goal_client
    await assign(client)
    assert (await client.post("/api/conversations/sessions/chat-1/archive")).status == 204
    _assert_paused(store)
    assert (await (await client.get("/api/goals")).json())["goals"] == []
    assert (await client.post(BASE + "/resume", json={})).status == 409
    assert (await client.post(BASE + "/run", json={})).status == 409
    assert (await assign(client)).status == 409
    assert (await client.post("/api/conversations/sessions/chat-1/unarchive")).status == 204
    _assert_paused(store)


async def test_delete_removes_goal_and_wake(goal_client):
    client, store, _, _ = goal_client
    await assign(client)
    assert (await client.delete("/api/conversations/sessions/chat-1")).status == 204
    assert store.list() == []
    assert store.due() == []


async def test_goals_api_is_unavailable_when_experiment_disabled(goal_client):
    client, store, _, enabled = goal_client
    enabled["value"] = False
    for method, path in [("get", BASE), ("get", "/api/goals"), ("post", BASE), ("patch", BASE),
                         ("post", BASE + "/run"), ("post", BASE + "/reopen"), ("get", BASE + "/history")]:
        response = await getattr(client, method)(path, json={"objective": "A goal"})
        assert response.status == 404
    assert store.list() == []


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
    running(runtime, "unrelated-turn")
    body = await (await client.get(BASE)).json()
    assert body["goal"]["paused"] is True
    assert body["goal"]["running"] is False
    assert body["goal"]["run_id"] is None


async def test_goal_run_is_shown_as_running(goal_client):
    client, store, runtime, _ = goal_client
    await assign(client)
    goal = store.current("chat-1")
    store.claim_for_turn(goal.id, "turn")
    store.bind_run(goal.id, "turn", "run-7")
    running(runtime, "run-7")
    body = await (await client.get(BASE)).json()
    assert body["running"] is True
    assert body["goal"]["run_id"] == "run-7"


@pytest.mark.parametrize("action", ["archive", "delete"])
async def test_conversation_removal_disarms_wake_before_files_change(goal_client, monkeypatch, action):
    client, store, _, _ = goal_client
    await assign(client)
    from server import _conversation_routes

    original = getattr(_conversation_routes, f"{action}_conversation")

    def checked_remove(conversation_id):
        assert store.due() == []
        latest = store.latest(conversation_id)
        assert latest.paused or latest.next.kind == "cancelled"
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
    store.update(seen_goal.id, seen_goal.revision, summary="More progress since the UI refreshed")
    response = await client.post(BASE + "/pause", json={"goal_id": seen_goal.id})
    assert response.status == 200
    _assert_paused(store)


async def test_old_control_cannot_pause_a_replacement_goal(goal_client):
    client, store, _, _ = goal_client
    await assign(client)
    old = completed(store, store.current("chat-1"))
    await assign(client, objective="Organize household tasks")
    response = await client.post(BASE + "/pause", json={"goal_id": old.id})
    assert response.status == 409
    assert store.current("chat-1").paused is False


async def test_controls_check_the_expected_revision(goal_client):
    client, store, _, _ = goal_client
    await assign(client)
    goal = store.current("chat-1")
    response = await client.post(BASE + "/pause", json={"expected_revision": goal.revision + 1})
    assert response.status == 409
    assert store.current("chat-1").paused is False


async def test_run_moves_future_wake_to_now(goal_client):
    client, store, _, _ = goal_client
    await assign(client)
    goal = scheduled(store, store.current("chat-1"))
    response = await client.post(BASE + "/run", json={})
    assert response.status == 200
    saved = (await response.json())["goal"]["next"]
    assert saved["id"] == goal.next.id and saved["reason"] == "run_now"
    assert [item.id for item in store.due()] == [goal.id]


async def test_run_from_error_sets_retry_wake(goal_client):
    client, store, _, _ = goal_client
    await assign(client)
    goal = failed(store, store.current("chat-1"))
    response = await client.post(BASE + "/run", json={})
    assert response.status == 200
    saved = (await response.json())["goal"]["next"]
    assert saved["kind"] == "wake" and saved["reason"] == "retry"
    assert [item.id for item in store.due()] == [goal.id]


async def test_run_refused_while_paused(goal_client):
    client, store, _, _ = goal_client
    await assign(client)
    goal = scheduled(store, store.current("chat-1"))
    store.pause(goal.id)
    response = await client.post(BASE + "/run", json={})
    assert response.status == 409
    assert store.get(goal.id).next == goal.next


async def test_run_refused_while_running(goal_client):
    client, store, runtime, _ = goal_client
    await assign(client)
    goal = scheduled(store, store.current("chat-1"))
    running(runtime)
    assert (await client.post(BASE + "/run", json={})).status == 409
    runtime.active_for_conversation.return_value = None
    store.claim_for_turn(goal.id, "turn")
    assert (await client.post(BASE + "/run", json={})).status == 409
    assert store.get(goal.id).next == goal.next


async def test_run_refused_on_an_ended_goal(goal_client):
    client, store, _, _ = goal_client
    await assign(client)
    done = completed(store, store.current("chat-1"))
    response = await client.post(BASE + "/run", json={})
    assert store.get(done.id) == done
    assert response.status == 409


async def test_reopen_starts_a_run_with_the_text_and_keeps_plan_and_history(goal_client):
    client, store, runtime, _ = goal_client
    await assign(client)
    goal = with_plan(store, store.current("chat-1"))
    done = completed(store, goal)
    response = await client.post(BASE + "/reopen", json={"goal_id": goal.id, "text": "  Also book a cleaning.  "})
    assert response.status == 200
    body = (await response.json())["goal"]
    assert body["next"] == {"kind": "wait", "question_ids": []}
    assert body["plan"] == [step.model_dump(mode="json") for step in done.plan]
    assert body["history_count"] == done.history_count + 1
    runtime.start.assert_awaited_once()
    request = runtime.start.await_args.args[0]
    assert request.message == "Also book a cleaning."
    assert request.conversation_id == "chat-1"
    assert request.profile_id == goal.profile_id
    assert request.goal_trigger is None
    assert store.due() == []


async def test_reopen_refused_while_running(goal_client):
    client, store, runtime, _ = goal_client
    await assign(client)
    done = completed(store, store.current("chat-1"))
    running(runtime)
    response = await client.post(BASE + "/reopen", json={"text": "Also book a cleaning."})
    assert response.status == 409
    assert store.get(done.id) == done
    runtime.start.assert_not_awaited()


async def test_reopen_refused_when_not_ended(goal_client):
    client, store, runtime, _ = goal_client
    await assign(client)
    goal = store.current("chat-1")
    response = await client.post(BASE + "/reopen", json={"text": "Also book a cleaning."})
    assert response.status == 409
    assert store.get(goal.id) == goal
    runtime.start.assert_not_awaited()


async def test_reopen_refused_for_an_older_goal(goal_client):
    client, store, runtime, _ = goal_client
    await assign(client)
    old = completed(store, store.current("chat-1"))
    await assign(client, objective="Plan household meals")
    newer = completed(store, store.current("chat-1"))
    response = await client.post(BASE + "/reopen", json={"goal_id": old.id, "text": "Try again."})
    assert response.status == 409
    assert store.get(old.id) == old and store.get(newer.id) == newer


async def test_reopen_needs_text(goal_client):
    client, store, runtime, _ = goal_client
    await assign(client)
    done = completed(store, store.current("chat-1"))
    assert (await client.post(BASE + "/reopen", json={"text": "   "})).status == 400
    assert store.get(done.id) == done


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
            assert store.current("chat-1").paused
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
        goal = store.update(goal.id, goal.revision, summary=f'Progress {index}')
    snapshot = await (await client.get(BASE)).json()
    assert snapshot['goal']['summary'] == 'Progress 59'
    assert snapshot['history'] == []
    url = BASE + '/history'
    first = await (await client.get(url, params={'goal_id': goal.id, 'q': 'Progress'})).json()
    second = await (await client.get(url, params={'goal_id': goal.id, 'q': 'Progress', 'before': first['next_before']})).json()
    assert len(first['entries']) == len(second['entries']) == 20
    assert not {e['id'] for e in first['entries']} & {e['id'] for e in second['entries']}
    assert {e['actor'] for e in first['entries']} == {'user'}
    match = await (await client.get(url, params={'goal_id': goal.id, 'q': 'Progress 0'})).json()
    assert match['entries'][0]['data']['after']['summary'] == 'Progress 0'
    other = store.create('other-chat', 'Private goal', 'assistant')
    assert (await client.get(url, params={'goal_id': other.id})).status == 404
    assert (await client.get(url, params={'goal_id': goal.id, 'before': '-1'})).status == 400
    enabled['value'] = False
    assert (await client.get(url, params={'goal_id': goal.id})).status == 404


@pytest.mark.parametrize("field,value", [
    ("constraints", "Mornings only"), ("success_criteria", ["Booked"]), ("kind", "ongoing"),
    ("status", "completed"), ("next", {"kind": "done", "outcome": "Forged"}), ("summary", "Forged"),
])
async def test_removed_or_agent_only_fields_are_rejected_by_assignment_and_edit(goal_client, field, value):
    client, store, _, _ = goal_client
    response = await assign(client, **{field: value})
    assert response.status == 400
    assert not store.list()
    goal = (await (await assign(client)).json())["goal"]
    response = await client.patch(BASE, json={"expected_revision": goal["revision"], field: value})
    assert response.status == 400
    assert store.current("chat-1").revision == goal["revision"]
