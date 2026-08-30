from unittest.mock import MagicMock

from agents import AgentProfile
from browser_profiles import _assignment


async def test_assignment_validates_metadata_but_loads_saved_state_lazily(monkeypatch):
    store = MagicMock()
    store.load_state.return_value = {"cookies": [], "origins": []}
    monkeypatch.setattr(_assignment, "get_browser_profile_store", lambda: store)

    assignment = await _assignment.resolve_browser_profile_assignment(
        AgentProfile(
            id="agent",
            name="Agent",
            browser_access=True,
            browser_profile_id="work",
        )
    )

    store.get.assert_called_once_with("work")
    store.load_state.assert_not_called()
    assert assignment.source_profile_id == "work"
    assert assignment.storage_state_loader is not None

    assert await assignment.storage_state_loader() == {"cookies": [], "origins": []}
    store.load_state.assert_called_once_with("work")


async def test_unavailable_assignment_uses_empty_without_a_loader(monkeypatch):
    store = MagicMock()
    store.get.side_effect = KeyError("missing")
    monkeypatch.setattr(_assignment, "get_browser_profile_store", lambda: store)

    assignment = await _assignment.resolve_browser_profile_assignment(
        AgentProfile(
            id="agent",
            name="Agent",
            browser_access=True,
            browser_profile_id="missing",
        )
    )

    assert assignment.source_profile_id is None
    assert assignment.storage_state_loader is None
    store.load_state.assert_not_called()
