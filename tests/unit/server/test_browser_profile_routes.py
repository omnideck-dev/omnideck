"""Security and lifecycle checks for Browser-profile HTTP routes."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from browser.profiles import BrowserProfile, BrowserProfileSite
from browser.runtime import AgentBrowserBinding
from server import _browser_profile_routes as routes


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


def _runtime(monkeypatch, *, binding_profile_id: str | None = "work"):
    runtime = MagicMock()
    runtime.profiles = MagicMock()
    runtime.get_conversation_browser = AsyncMock(return_value=MagicMock())
    runtime.get_conversation_binding = AsyncMock(
        return_value=AgentBrowserBinding(
            agent_profile_id="agent-a",
            browser_profile_id=binding_profile_id,
        ),
    )
    runtime.save_browser_to_existing = AsyncMock(return_value=_profile())
    runtime.save_browser_as_new = AsyncMock(return_value=_profile("new-profile"))
    runtime.save_user_browser_to_existing = AsyncMock(return_value=_profile("default"))
    runtime.preview_user_browser = AsyncMock(
        return_value=[BrowserProfileSite(domain="example.test", cookies=1)],
    )
    runtime.agent_profiles_using_live_profile = AsyncMock(return_value=set())
    runtime.assign_profile_to_live_conversation = AsyncMock()
    runtime.user_browser_profile_id = None
    monkeypatch.setattr(routes, "get_browser_runtime", lambda: runtime)
    return runtime


@pytest.mark.unit
async def test_request_validation_rejects_non_text_profile_name():
    with pytest.raises(web.HTTPBadRequest):
        await routes.handle_save_browser_session(_request(json_body={"name": 42}))


@pytest.mark.unit
async def test_load_browser_session_requires_an_explicit_profile_id():
    with pytest.raises(web.HTTPBadRequest):
        await routes.handle_load_browser_session(_request(json_body={}))


@pytest.mark.unit
async def test_empty_takeover_cannot_overwrite_an_existing_profile(monkeypatch):
    runtime = _runtime(monkeypatch, binding_profile_id="empty")

    response = await routes.handle_save_takeover(
        _request(json_body={"profile_id": "default"}),
    )

    assert response.status == 409
    assert "loaded profile" in json.loads(response.body)["error"]
    runtime.save_browser_to_existing.assert_not_awaited()


@pytest.mark.unit
async def test_takeover_can_only_update_its_loaded_profile(monkeypatch):
    runtime = _runtime(monkeypatch)

    response = await routes.handle_save_takeover(
        _request(json_body={"profile_id": "personal"}),
    )

    assert response.status == 409
    runtime.save_browser_to_existing.assert_not_awaited()


@pytest.mark.unit
async def test_takeover_updates_its_loaded_profile(monkeypatch):
    runtime = _runtime(monkeypatch)
    browser = await runtime.get_conversation_browser("conversation-1")

    response = await routes.handle_save_takeover(
        _request(json_body={"profile_id": "work"}),
    )

    assert response.status == 200
    runtime.save_browser_to_existing.assert_awaited_once_with(browser, "work")


@pytest.mark.unit
async def test_new_takeover_snapshot_does_not_rebind_without_confirmation(monkeypatch):
    runtime = _runtime(monkeypatch)
    save_agent = MagicMock()
    monkeypatch.setattr(routes, "save_agent_profile", save_agent)

    response = await routes.handle_save_takeover(
        _request(json_body={"name": "Snapshot", "assign_to_agent": False}),
    )

    assert response.status == 200
    save_agent.assert_not_called()
    runtime.assign_profile_to_live_conversation.assert_not_awaited()
    binding = await runtime.get_conversation_binding("conversation-1")
    assert binding.browser_profile_id == "work"


@pytest.mark.unit
async def test_new_takeover_snapshot_rebinds_only_when_assigned(monkeypatch):
    runtime = _runtime(monkeypatch)
    agent = SimpleNamespace(
        id="agent-a",
        model_copy=MagicMock(return_value=SimpleNamespace(browser_profile_id="new-profile")),
    )
    monkeypatch.setattr(routes, "get_agent_profile", lambda _profile_id: agent)
    save_agent = MagicMock()
    monkeypatch.setattr(routes, "save_agent_profile", save_agent)

    response = await routes.handle_save_takeover(
        _request(json_body={"name": "Snapshot", "assign_to_agent": True}),
    )

    assert response.status == 200
    save_agent.assert_called_once()
    runtime.assign_profile_to_live_conversation.assert_awaited_once_with(
        "conversation-1",
        "new-profile",
    )


@pytest.mark.unit
async def test_save_captures_current_user_browser_state_at_confirmation(monkeypatch):
    runtime = _runtime(monkeypatch)

    response = await routes.handle_save_browser_session(
        _request(json_body={"profile_id": "default"}),
    )

    assert response.status == 200
    runtime.save_user_browser_to_existing.assert_awaited_once_with("default")


@pytest.mark.unit
async def test_preview_returns_loaded_profile_and_site_summary(monkeypatch):
    runtime = _runtime(monkeypatch)
    runtime.user_browser_profile_id = "work"

    response = await routes.handle_preview_browser_session(_request())

    assert response.status == 200
    assert json.loads(response.body) == {
        "browser_profile_id": "work",
        "sites": [
            {
                "domain": "example.test",
                "cookies": 1,
                "local_storage": False,
                "indexed_db": False,
            },
        ],
    }


@pytest.mark.unit
async def test_remove_sites_requires_a_non_empty_domain_list():
    with pytest.raises(web.HTTPBadRequest):
        await routes.handle_remove_browser_profile_sites(
            _request(json_body={"domains": []}),
        )


@pytest.mark.unit
async def test_remove_sites_updates_the_saved_profile(monkeypatch):
    runtime = _runtime(monkeypatch)
    runtime.profiles.remove_domains.return_value = _profile()

    response = await routes.handle_remove_browser_profile_sites(
        _request(json_body={"domains": ["example.test", "auth.example.test"]}),
    )

    assert response.status == 200
    runtime.profiles.remove_domains.assert_called_once_with(
        "work",
        ["example.test", "auth.example.test"],
    )


@pytest.mark.unit
async def test_clear_state_updates_the_saved_profile(monkeypatch):
    runtime = _runtime(monkeypatch)
    runtime.profiles.clear_state.return_value = _profile()

    response = await routes.handle_clear_browser_profile_state(_request())

    assert response.status == 200
    runtime.profiles.clear_state.assert_called_once_with("work")


@pytest.mark.unit
async def test_delete_rejects_profile_loaded_in_user_browser(monkeypatch):
    runtime = _runtime(monkeypatch)
    runtime.user_browser_profile_id = "work"
    monkeypatch.setattr(routes, "list_agent_profiles", lambda **_kwargs: [])

    response = await routes.handle_delete_browser_profile(_request())

    assert response.status == 409
    assert json.loads(response.body) == {
        "error": "This browser profile is in use",
        "usage": {"loaded_in_browser": True, "agents": []},
    }
    runtime.profiles.delete.assert_not_called()


@pytest.mark.unit
async def test_delete_rejects_assigned_or_live_agent_profiles(monkeypatch):
    runtime = _runtime(monkeypatch)
    runtime.agent_profiles_using_live_profile.return_value = {"live-agent"}
    agent_profiles = [
        SimpleNamespace(id="assigned-agent", name="Recruiting", browser_profile_id="work"),
        SimpleNamespace(id="live-agent", name="Research", browser_profile_id="default"),
    ]
    monkeypatch.setattr(routes, "list_agent_profiles", lambda **_kwargs: agent_profiles)

    response = await routes.handle_delete_browser_profile(_request())

    assert response.status == 409
    assert json.loads(response.body)["usage"] == {
        "loaded_in_browser": False,
        "agents": ["Recruiting", "Research"],
    }
    runtime.profiles.delete.assert_not_called()


@pytest.mark.unit
async def test_delete_succeeds_after_profile_is_no_longer_in_use(monkeypatch):
    runtime = _runtime(monkeypatch)
    monkeypatch.setattr(routes, "list_agent_profiles", lambda **_kwargs: [])

    response = await routes.handle_delete_browser_profile(_request())

    assert response.status == 204
    runtime.profiles.delete.assert_called_once_with("work")
