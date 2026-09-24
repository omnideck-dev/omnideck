from unittest.mock import AsyncMock, MagicMock

import pytest

from browser.profile_store import EMPTY_BROWSER_PROFILE_ID
from browser.runtime import BrowserRuntime
from browser.session_pool import BrowserSessionPool


def _runtime(monkeypatch, *, key: str = "conversation:one"):
    profiles = MagicMock()
    sessions = AsyncMock(spec=BrowserSessionPool)
    runtime = BrowserRuntime(profiles, sessions)
    monkeypatch.setattr(runtime, "_current_agent_browser_key", lambda: key)
    return runtime, profiles, sessions


def test_root_agent_key_is_scoped_to_conversation(monkeypatch):
    monkeypatch.setattr("browser.runtime.get_conversation_id", lambda: "conversation-1")
    monkeypatch.setattr("browser.runtime.get_current_depth", lambda: 0)
    monkeypatch.setattr("browser.runtime.get_current_agent_id", lambda: "root.agent.1")

    assert BrowserRuntime._current_agent_browser_key() == "conversation:conversation-1"


def test_subagent_key_is_scoped_to_runtime_agent(monkeypatch):
    monkeypatch.setattr("browser.runtime.get_conversation_id", lambda: "conversation-1")
    monkeypatch.setattr("browser.runtime.get_current_depth", lambda: 1)
    monkeypatch.setattr("browser.runtime.get_current_agent_id", lambda: "root.child.2")

    assert BrowserRuntime._current_agent_browser_key() == "root.child.2"


def test_agent_key_requires_an_active_execution(monkeypatch):
    monkeypatch.setattr("browser.runtime.get_conversation_id", lambda: None)
    monkeypatch.setattr("browser.runtime.get_current_depth", lambda: 0)
    monkeypatch.setattr("browser.runtime.get_current_agent_id", lambda: None)

    with pytest.raises(RuntimeError, match="outside an agent execution"):
        BrowserRuntime._current_agent_browser_key()


async def test_saved_profile_is_validated_but_loaded_lazily(monkeypatch):
    runtime, profiles, sessions = _runtime(monkeypatch)
    profiles.load_state.return_value = {"cookies": [], "origins": []}

    binding = await runtime.prepare_current_agent_browser(
        agent_profile_id="agent",
        browser_profile_id="work",
    )

    profiles.get.assert_called_once_with("work")
    profiles.load_state.assert_not_called()
    assert binding.browser_profile_id == "work"
    loader = sessions.prepare.await_args.args[1]
    assert await loader() == {"cookies": [], "origins": []}
    profiles.load_state.assert_called_once_with("work")


async def test_unavailable_profile_falls_back_to_empty(monkeypatch):
    runtime, profiles, sessions = _runtime(monkeypatch)
    profiles.get.side_effect = KeyError("missing")

    binding = await runtime.prepare_current_agent_browser(
        agent_profile_id="agent",
        browser_profile_id="missing",
    )

    assert binding.browser_profile_id == EMPTY_BROWSER_PROFILE_ID
    sessions.prepare.assert_awaited_once_with("conversation:one", None)
    profiles.load_state.assert_not_called()


async def test_get_agent_browser_requires_prepared_access(monkeypatch):
    runtime, _profiles, sessions = _runtime(monkeypatch)

    with pytest.raises(RuntimeError, match="was not prepared"):
        await runtime.get_current_agent_browser()

    await runtime.prepare_current_agent_browser(
        agent_profile_id="agent",
        browser_profile_id=None,
    )
    with pytest.raises(RuntimeError, match="disabled"):
        await runtime.get_current_agent_browser()

    sessions.get_or_create.assert_not_awaited()


async def test_same_binding_reuses_live_session(monkeypatch):
    runtime, _profiles, sessions = _runtime(monkeypatch)

    await runtime.prepare_current_agent_browser(
        agent_profile_id="agent-a",
        browser_profile_id=EMPTY_BROWSER_PROFILE_ID,
    )
    await runtime.prepare_current_agent_browser(
        agent_profile_id="agent-a",
        browser_profile_id=EMPTY_BROWSER_PROFILE_ID,
    )

    sessions.release.assert_not_awaited()


async def test_switching_agents_releases_even_when_both_use_empty(monkeypatch):
    runtime, _profiles, sessions = _runtime(monkeypatch)
    await runtime.prepare_current_agent_browser(
        agent_profile_id="agent-a",
        browser_profile_id=EMPTY_BROWSER_PROFILE_ID,
    )

    binding = await runtime.prepare_current_agent_browser(
        agent_profile_id="agent-b",
        browser_profile_id=EMPTY_BROWSER_PROFILE_ID,
    )

    sessions.release.assert_awaited_once_with("conversation:one")
    assert binding.agent_profile_id == "agent-b"


async def test_saving_new_snapshot_does_not_rebind_live_agent(monkeypatch):
    runtime, profiles, _sessions = _runtime(monkeypatch)
    browser = AsyncMock()
    browser.capture_storage_state.return_value = {"cookies": [], "origins": []}
    profiles.create.return_value = MagicMock(id="new-profile")
    await runtime.prepare_current_agent_browser(
        agent_profile_id="agent",
        browser_profile_id="work",
    )

    await runtime.save_browser_as_new(browser, name="Copy", icon="bi-globe2")

    binding = await runtime.get_conversation_binding("one")
    assert binding is not None
    assert binding.browser_profile_id == "work"


async def test_explicit_assignment_rebinds_unchanged_live_session(monkeypatch):
    runtime, _profiles, sessions = _runtime(monkeypatch)
    await runtime.prepare_current_agent_browser(
        agent_profile_id="agent",
        browser_profile_id="work",
    )

    await runtime.assign_profile_to_live_conversation("one", "new-profile")

    binding = await runtime.get_conversation_binding("one")
    assert binding is not None
    assert binding.browser_profile_id == "new-profile"
    sessions.release.assert_not_awaited()


async def test_live_profile_usage_includes_root_and_subagent_sessions(monkeypatch):
    runtime, _profiles, sessions = _runtime(monkeypatch)
    sessions.get.return_value = object()
    await runtime.prepare_current_agent_browser(
        agent_profile_id="root-agent",
        browser_profile_id="work",
    )
    monkeypatch.setattr(runtime, "_current_agent_browser_key", lambda: "root.child.1")
    await runtime.prepare_current_agent_browser(
        agent_profile_id="child-agent",
        browser_profile_id="work",
    )

    assert await runtime.agent_profiles_using_live_profile("work") == {
        "root-agent",
        "child-agent",
    }


async def test_profile_usage_excludes_prepared_but_unopened_sessions(monkeypatch):
    runtime, _profiles, sessions = _runtime(monkeypatch)
    await runtime.prepare_current_agent_browser(
        agent_profile_id="agent",
        browser_profile_id="work",
    )
    sessions.get.return_value = None

    assert await runtime.agent_profiles_using_live_profile("work") == set()
