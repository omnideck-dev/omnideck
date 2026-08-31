"""Security and provenance checks for Browser-profile HTTP routes."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from browser_profiles import _conversation as sessions
from browser_profiles._models import BrowserProfile
from server import _browser_profile_routes as routes


@pytest.fixture(autouse=True)
def _clear_conversation_sessions():
    sessions.reset_conversation_browser_sessions()
    yield
    sessions.reset_conversation_browser_sessions()


def _request(
    *,
    conversation_id: str = "conversation-1",
    profile_id: str = "work",
    json_body: dict | None = None,
):
    request = MagicMock()
    request.match_info = {"conversation_id": conversation_id, "id": profile_id}
    request.json = AsyncMock(return_value=json_body or {})
    return request


def _profile(profile_id: str = "work") -> BrowserProfile:
    return BrowserProfile(
        id=profile_id,
        name="Work",
        icon="bi-briefcase",
        created_at="2026-08-28T00:00:00+00:00",
        updated_at="2026-08-28T00:00:00+00:00",
    )


@pytest.mark.unit
async def test_request_validation_rejects_non_text_profile_name():
    with pytest.raises(web.HTTPBadRequest):
        await routes.handle_save_browser_session(_request(json_body={"name": 42}))


@pytest.mark.unit
async def test_empty_takeover_cannot_overwrite_an_existing_profile(monkeypatch):
    browser = MagicMock()
    monkeypatch.setattr(
        routes,
        "get_browser_by_conversation_id",
        AsyncMock(return_value=browser),
    )
    save = AsyncMock()
    monkeypatch.setattr(routes, "save_browser_context_to_existing", save)
    await sessions.prepare_conversation_browser(
        "conversation-1",
        agent_profile_id="agent-a",
        browser_access=True,
        configured_profile_id=None,
        source_profile_id=None,
    )

    response = await routes.handle_save_takeover(
        _request(json_body={"profile_id": "default"}),
    )

    assert response.status == 409
    assert "loaded profile" in json.loads(response.body)["error"]
    save.assert_not_awaited()


@pytest.mark.unit
async def test_takeover_can_only_update_the_profile_that_seeded_live_state(monkeypatch):
    browser = MagicMock()
    monkeypatch.setattr(
        routes,
        "get_browser_by_conversation_id",
        AsyncMock(return_value=browser),
    )
    save = AsyncMock()
    monkeypatch.setattr(routes, "save_browser_context_to_existing", save)
    await sessions.prepare_conversation_browser(
        "conversation-1",
        agent_profile_id="agent-a",
        browser_access=True,
        configured_profile_id="work",
        source_profile_id="work",
    )

    response = await routes.handle_save_takeover(
        _request(json_body={"profile_id": "personal"}),
    )

    assert response.status == 409
    save.assert_not_awaited()


@pytest.mark.unit
async def test_takeover_updates_its_actual_source_profile(monkeypatch):
    browser = MagicMock()
    monkeypatch.setattr(
        routes,
        "get_browser_by_conversation_id",
        AsyncMock(return_value=browser),
    )
    save = AsyncMock(return_value=_profile())
    monkeypatch.setattr(routes, "save_browser_context_to_existing", save)
    await sessions.prepare_conversation_browser(
        "conversation-1",
        agent_profile_id="agent-a",
        browser_access=True,
        configured_profile_id="work",
        source_profile_id="work",
    )

    response = await routes.handle_save_takeover(
        _request(json_body={"profile_id": "work"}),
    )

    assert response.status == 200
    save.assert_awaited_once_with(browser, "work", storage_state=None)


@pytest.mark.unit
async def test_expired_preview_is_not_silently_recaptured(monkeypatch):
    browser = MagicMock()
    monkeypatch.setattr(routes, "ensure_user_browser", AsyncMock(return_value=browser))
    save = AsyncMock()
    monkeypatch.setattr(routes, "save_user_browser_to_existing", save)

    response = await routes.handle_save_browser_session(
        _request(json_body={"profile_id": "default", "preview_token": "expired"}),
    )

    assert response.status == 409
    assert "Browser changed" in json.loads(response.body)["error"]
    save.assert_not_awaited()


@pytest.mark.unit
async def test_remove_sites_requires_a_non_empty_domain_list():
    with pytest.raises(web.HTTPBadRequest):
        await routes.handle_remove_browser_profile_sites(
            _request(json_body={"domains": []}),
        )


@pytest.mark.unit
async def test_remove_sites_updates_the_saved_profile(monkeypatch):
    store = MagicMock()
    store.remove_domains.return_value = _profile()
    monkeypatch.setattr(routes, "get_browser_profile_store", lambda: store)

    response = await routes.handle_remove_browser_profile_sites(
        _request(json_body={"domains": ["example.test", "auth.example.test"]}),
    )

    assert response.status == 200
    store.remove_domains.assert_called_once_with(
        "work",
        ["example.test", "auth.example.test"],
    )


@pytest.mark.unit
async def test_clear_state_updates_the_saved_profile(monkeypatch):
    store = MagicMock()
    store.clear_state.return_value = _profile()
    monkeypatch.setattr(routes, "get_browser_profile_store", lambda: store)

    response = await routes.handle_clear_browser_profile_state(_request())

    assert response.status == 200
    store.clear_state.assert_called_once_with("work")


@pytest.mark.unit
async def test_delete_rejects_profile_loaded_in_user_browser(monkeypatch):
    store = MagicMock()
    monkeypatch.setattr(routes, "get_browser_profile_store", lambda: store)
    monkeypatch.setattr(routes, "list_agent_profiles", lambda **_kwargs: [])
    monkeypatch.setattr(routes, "get_user_browser_source_profile_id", lambda: "work")

    response = await routes.handle_delete_browser_profile(_request())

    assert response.status == 409
    assert json.loads(response.body) == {
        "error": "This browser profile is in use",
        "usage": {"loaded_in_browser": True, "agents": []},
    }
    store.delete.assert_not_called()


@pytest.mark.unit
async def test_delete_rejects_profile_assigned_to_agents(monkeypatch):
    store = MagicMock()
    assigned = SimpleNamespace(
        name="Recruiting",
        browser_access=True,
        browser_profile_id="work",
    )
    monkeypatch.setattr(routes, "get_browser_profile_store", lambda: store)
    monkeypatch.setattr(routes, "list_agent_profiles", lambda **_kwargs: [assigned])
    monkeypatch.setattr(routes, "get_user_browser_source_profile_id", lambda: None)

    response = await routes.handle_delete_browser_profile(_request())

    assert response.status == 409
    assert json.loads(response.body)["usage"] == {
        "loaded_in_browser": False,
        "agents": ["Recruiting"],
    }
    store.delete.assert_not_called()


@pytest.mark.unit
async def test_delete_combines_browser_and_agent_usage(monkeypatch):
    store = MagicMock()
    assigned = SimpleNamespace(
        name="Recruiting",
        browser_access=True,
        browser_profile_id="work",
    )
    monkeypatch.setattr(routes, "get_browser_profile_store", lambda: store)
    monkeypatch.setattr(routes, "list_agent_profiles", lambda **_kwargs: [assigned])
    monkeypatch.setattr(routes, "get_user_browser_source_profile_id", lambda: "work")

    response = await routes.handle_delete_browser_profile(_request())

    assert response.status == 409
    assert json.loads(response.body)["usage"] == {
        "loaded_in_browser": True,
        "agents": ["Recruiting"],
    }
    store.delete.assert_not_called()


@pytest.mark.unit
async def test_delete_succeeds_after_profile_is_no_longer_in_use(monkeypatch):
    store = MagicMock()
    monkeypatch.setattr(routes, "get_browser_profile_store", lambda: store)
    monkeypatch.setattr(routes, "list_agent_profiles", lambda **_kwargs: [])
    monkeypatch.setattr(routes, "get_user_browser_source_profile_id", lambda: None)

    response = await routes.handle_delete_browser_profile(_request())

    assert response.status == 204
    store.delete.assert_called_once_with("work")
