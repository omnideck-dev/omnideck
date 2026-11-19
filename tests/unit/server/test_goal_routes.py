"""Goal HTTP behavior, including experiment gating and conversation lifecycle."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from agents import AgentProfile
from conversations import (
    ConversationStore, conversation_exists, conversations_dir, list_conversations, load_conversation_profile,
    save_conversation_profile,
)
from goals import GoalStep, GoalStore
from server._agent_runtime import AGENT_RUNTIME_KEY
from server._agent_run_routes import register_agent_run_routes
from server._conversation_routes import register_conversation_routes
from server._goal_routes import register_goal_routes
from server._goals import GOAL_FEED_KEY, GOAL_STORE_KEY, GoalActivityFeed
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
    store = GoalStore(conversations_dir())
    runtime = MagicMock()
    runtime.active_for_conversation.return_value = None
    runtime.start = AsyncMock()
    runtime.conversations = ConversationStore()
    app = web.Application(middlewares=[cors_and_error_middleware])
    app[GOAL_STORE_KEY] = store
    app[GOAL_FEED_KEY] = GoalActivityFeed(store, lambda: enabled["value"])
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
    assert "running" not in goal and "profile_id" not in goal
    assert store.due()[0].id == goal["id"]
    assert conversation_exists("chat-1")
    assert list_conversations()[0].title == "Find a dentist and book an appointment"


async def test_only_one_unfinished_goal_and_ended_history_survives(goal_client):
    client, store, _, _ = goal_client
    assert (await assign(client)).status == 201
    assert (await assign(client)).status == 409
    completed(store, store.current("chat-1"), "Appointment confirmed for Tuesday")
    assert (await assign(client, objective="Plan household meals")).status == 201
    body = await (await client.get(BASE)).json()
    assert body["goal"]["objective"] == "Plan household meals"
    assert "running" not in body
    assert len(body["earlier_goals"]) == 1
    assert body["earlier_goals"][0]["next"] == {"kind": "done", "outcome": "Appointment confirmed for Tuesday"}


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
    assert store.current("chat-1") is None and store.due() == []
    assert [goal.paused for goal in store.list()] == [True]
    assert (await assign(client)).status == 400
    assert (await client.post("/api/conversations/sessions/chat-1/unarchive")).status == 204
    _assert_paused(store)
    assert store.due() == []


async def test_delete_removes_goal_and_wake(goal_client):
    client, store, _, _ = goal_client
    await assign(client)
    assert (await client.delete("/api/conversations/sessions/chat-1")).status == 204
    assert store.list() == []
    assert store.due() == []


async def test_goals_api_is_unavailable_when_experiment_disabled(goal_client):
    client, store, _, enabled = goal_client
    enabled["value"] = False
    for method, path in [("get", BASE), ("post", BASE), ("patch", BASE), ("post", BASE + "/run"),
                         ("post", BASE + "/pause"), ("post", BASE + "/reopen"), ("post", BASE + "/answers"),
                         ("get", BASE + "/history")]:
        response = await getattr(client, method)(path, json={"objective": "A goal"})
        assert response.status == 403
        assert await response.json() == {"error": "Goals are turned off."}
    assert store.list() == []


async def test_invalid_assignment_does_not_create_conversation_or_wake(goal_client):
    client, store, _, _ = goal_client
    response = await assign(client, objective="   ")
    assert response.status == 400
    assert not conversation_exists("chat-1")
    assert store.list() == []


async def test_edit_and_pause_on_a_goal_whose_file_is_gone_return_404(goal_client):
    import shutil

    client, store, _, _ = goal_client
    await assign(client)
    goal = store.current("chat-1")
    shutil.rmtree(store._base / "chat-1" / "goals" / goal.id)
    response = await client.patch(BASE, json={"expected_revision": goal.revision, "objective": "Changed"})
    assert response.status == 404
    assert (await client.post(BASE + "/pause", json={})).status == 404


async def test_a_body_with_a_bad_field_returns_400_with_one_sentence(goal_client):
    client, _store, _, _ = goal_client
    response = await client.post(BASE, json={"objective": "Find a dentist", "deadline": "Friday"})
    assert response.status == 400
    assert (await response.json()) == {"error": "Extra inputs are not permitted"}


async def test_edit_while_a_run_holds_the_goal_returns_409_with_the_sentence(goal_client):
    client, store, _, _ = goal_client
    await assign(client)
    goal = store.claim_for_turn(store.current("chat-1").id, "turn")
    response = await client.patch(BASE, json={"expected_revision": goal.revision, "objective": "Changed"})
    assert response.status == 409
    assert (await response.json())["error"] == (
        "The agent is working on this goal. Pause it to edit now, or wait for it to finish."
    )


async def test_archive_pauses_the_goal_before_the_folder_moves(goal_client, monkeypatch):
    client, store, _, _ = goal_client
    await assign(client)
    from server import _conversation_routes

    original = _conversation_routes.archive_conversation

    def checked_archive(conversation_id):
        assert store.due() == []
        assert store.latest(conversation_id).paused
        return original(conversation_id)

    monkeypatch.setattr(_conversation_routes, "archive_conversation", checked_archive)
    assert (await client.post("/api/conversations/sessions/chat-1/archive")).status == 204


async def test_delete_writes_no_goal_file_before_the_folder_is_removed(goal_client, monkeypatch):
    client, store, _, _ = goal_client
    await assign(client)
    goal = store.current("chat-1")
    from server import _conversation_routes

    original = _conversation_routes.delete_conversation

    def checked_delete(conversation_id):
        assert store.latest(conversation_id) == goal
        return original(conversation_id)

    monkeypatch.setattr(_conversation_routes, "delete_conversation", checked_delete)
    assert (await client.delete("/api/conversations/sessions/chat-1")).status == 204
    assert store.current("chat-1") is None and store.latest_goals() == []


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


async def test_control_with_an_expected_revision_is_refused_as_unknown(goal_client):
    client, store, _, _ = goal_client
    await assign(client)
    goal = store.current("chat-1")
    response = await client.post(BASE + "/pause", json={"expected_revision": goal.revision})
    assert response.status == 400
    assert store.current("chat-1").paused is False


def only_these_agents(monkeypatch, *ids):
    agents = {id: AgentProfile(id=id, name=id, provider="fake", model="fake") for id in ids}
    monkeypatch.setattr("server._goal_routes.get_agent_profile", agents.get)


async def test_resume_after_the_chat_agent_was_deleted_waits_for_another_agent(goal_client, monkeypatch):
    client, store, _, _ = goal_client
    await assign(client)
    goal = store.current("chat-1")
    store.pause(goal.id)
    only_these_agents(monkeypatch, "other")
    refused = await client.post(BASE + "/resume", json={"goal_id": goal.id, "profile_id": "test"})
    assert refused.status == 400
    assert (await refused.json())["error"] == "This chat's agent was deleted or turned off. Choose another agent in the chat."
    assert store.get(goal.id).paused is True
    response = await client.post(BASE + "/resume", json={"goal_id": goal.id, "profile_id": "other"})
    assert response.status == 200
    assert (await response.json())["goal"]["paused"] is False
    assert load_conversation_profile("chat-1") == "other"


async def test_resume_without_a_picked_agent_checks_the_chat_saved_agent(goal_client, monkeypatch):
    client, store, _, _ = goal_client
    await assign(client)
    goal = store.current("chat-1")
    store.pause(goal.id)
    save_conversation_profile("chat-1", "deleted")
    only_these_agents(monkeypatch, "test")
    assert (await client.post(BASE + "/resume", json={})).status == 400
    assert store.get(goal.id).paused is True


async def test_retry_with_a_new_agent_saves_it_for_the_next_wake(goal_client, monkeypatch):
    client, store, _, _ = goal_client
    await assign(client)
    goal = failed(store, store.current("chat-1"))
    only_these_agents(monkeypatch, "other")
    response = await client.post(BASE + "/run", json={"goal_id": goal.id, "profile_id": "other"})
    assert response.status == 200
    assert (await response.json())["goal"]["next"]["reason"] == "retry"
    assert load_conversation_profile("chat-1") == "other"


async def test_refused_run_does_not_change_the_chat_agent(goal_client, monkeypatch):
    client, store, _, _ = goal_client
    await assign(client)
    goal = scheduled(store, store.current("chat-1"))
    store.pause(goal.id)
    only_these_agents(monkeypatch, "test", "other")
    assert (await client.post(BASE + "/run", json={"profile_id": "other"})).status == 409
    assert load_conversation_profile("chat-1") == "test"


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
    assert request.profile_id == "test"
    assert request.trigger is None
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
        assert response.status == 403
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
    assert snapshot['earlier_goals'] == []
    url = BASE + '/history'
    first = await (await client.get(url, params={'goal_id': goal.id, 'q': 'Progress'})).json()
    second = await (await client.get(url, params={'goal_id': goal.id, 'q': 'Progress', 'before': first['next_before']})).json()
    assert len(first['entries']) == len(second['entries']) == 20
    assert not {e['id'] for e in first['entries']} & {e['id'] for e in second['entries']}
    assert {e['actor'] for e in first['entries']} == {'user'}
    match = await (await client.get(url, params={'goal_id': goal.id, 'q': 'Progress 0'})).json()
    assert match['entries'][0]['data']['summary'] == 'Progress 0'
    other = store.create('other-chat', 'Private goal')
    assert (await client.get(url, params={'goal_id': other.id})).status == 404
    assert (await client.get(url, params={'goal_id': goal.id, 'before': '-1'})).status == 400
    enabled['value'] = False
    assert (await client.get(url, params={'goal_id': goal.id})).status == 403


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


async def test_answers_with_no_profile_use_the_chat_saved_profile(goal_client):
    from unittest.mock import AsyncMock

    from agent_runtime import QueuedMessage
    from tests.unit.goals.support import ask, choose

    client, store, runtime, _ = goal_client
    await assign(client)
    goal = store.claim_for_turn(store.current("chat-1").id, "turn")
    goal = ask(store, goal, "turn", "day", "Which day works?")
    choose(store, goal, "turn", action="wait_for_input", question_ids=["day"])
    store.finish_run(goal.id, "turn", "run-0", "success")
    runtime.send = AsyncMock(return_value=QueuedMessage("nudge", "run-1"))
    response = await client.post(BASE + "/answers", json={"goal_id": goal.id, "answers": [
        {"question_id": "day", "question_revision": 1, "answer": "Saturday"},
    ]})
    assert response.status == 202
    request = runtime.send.await_args.args[0]
    assert request.profile_id == "test"
    assert request.message == "Saturday"
    assert request.model_text.startswith("[Answers to your goal questions]")


async def test_answers_refused_when_goals_turn_off_during_the_body_read(goal_client, monkeypatch):
    from unittest.mock import AsyncMock

    client, store, runtime, enabled = goal_client
    await assign(client)
    runtime.send = AsyncMock()
    original_text = web.Request.text

    async def turn_off_while_reading(request):
        text = await original_text(request)
        enabled["value"] = False
        return text

    monkeypatch.setattr(web.Request, "text", turn_off_while_reading)
    response = await client.post(BASE + "/answers", json={"goal_id": store.current("chat-1").id, "answers": [
        {"question_id": "day", "question_revision": 1, "answer": "Saturday"},
    ]})
    assert response.status == 403
    runtime.send.assert_not_awaited()
