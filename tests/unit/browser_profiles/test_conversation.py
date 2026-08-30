from unittest.mock import AsyncMock

import pytest

from browser_profiles import _conversation as sessions


@pytest.fixture(autouse=True)
def _clear_sessions():
    sessions.reset_conversation_browser_sessions()
    yield
    sessions.reset_conversation_browser_sessions()


async def test_same_agent_assignment_reuses_conversation_browser(monkeypatch):
    release = AsyncMock()
    monkeypatch.setattr(sessions, "release_conversation_browser", release)

    await sessions.prepare_conversation_browser(
        "conversation-1",
        agent_profile_id="agent-a",
        browser_access=True,
        configured_profile_id="work",
        source_profile_id="work",
    )
    current = await sessions.prepare_conversation_browser(
        "conversation-1",
        agent_profile_id="agent-a",
        browser_access=True,
        configured_profile_id="work",
        source_profile_id="work",
    )

    release.assert_not_awaited()
    assert current.source_profile_id == "work"


async def test_switching_agents_replaces_even_when_both_use_empty(monkeypatch):
    release = AsyncMock()
    monkeypatch.setattr(sessions, "release_conversation_browser", release)
    await sessions.prepare_conversation_browser(
        "conversation-1",
        agent_profile_id="agent-a",
        browser_access=True,
        configured_profile_id=None,
        source_profile_id=None,
    )

    current = await sessions.prepare_conversation_browser(
        "conversation-1",
        agent_profile_id="agent-b",
        browser_access=True,
        configured_profile_id=None,
        source_profile_id=None,
    )

    release.assert_awaited_once_with("conversation-1")
    assert current.agent_profile_id == "agent-b"


async def test_save_as_new_updates_provenance_without_resetting_same_assignment(monkeypatch):
    release = AsyncMock()
    monkeypatch.setattr(sessions, "release_conversation_browser", release)
    await sessions.prepare_conversation_browser(
        "conversation-1",
        agent_profile_id="agent-a",
        browser_access=True,
        configured_profile_id=None,
        source_profile_id=None,
    )
    sessions.set_conversation_browser_source_profile_id(
        "conversation-1",
        "new-profile",
    )

    current = await sessions.prepare_conversation_browser(
        "conversation-1",
        agent_profile_id="agent-a",
        browser_access=True,
        configured_profile_id=None,
        source_profile_id=None,
    )

    release.assert_not_awaited()
    assert current.source_profile_id == "new-profile"


async def test_deleted_profile_is_detached_from_live_provenance():
    await sessions.prepare_conversation_browser(
        "conversation-1",
        agent_profile_id="agent-a",
        browser_access=True,
        configured_profile_id="old-profile",
        source_profile_id="old-profile",
    )

    sessions.detach_deleted_browser_profile("old-profile")

    current = sessions.get_conversation_browser_session("conversation-1")
    assert current is not None
    assert current.source_profile_id is None
