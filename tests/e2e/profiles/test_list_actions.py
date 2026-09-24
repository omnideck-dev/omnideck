"""E2E tests for the Agents list-row actions and the unsaved-changes guard.

Covers the interactions that live on the list (not the editor): inline
two-click delete, inline duplicate, and the guard shown when leaving the
editor with unsaved edits.
"""

from playwright.sync_api import Page, expect

from tests.e2e.pages import AgentsPage


def _create_profile(page: Page, profile_id: str, name: str) -> None:
    page.request.post("/api/profiles", data={
        "id": profile_id,
        "name": name,
        "description": "list-action e2e",
        "model": "",
        "skills": [],
    })


def _delete_profile(page: Page, profile_id: str) -> None:
    page.request.delete(f"/api/profiles/{profile_id}", fail_on_status_code=False)


def test_delete_from_list(page: Page):
    """Two-click delete on a list row removes the agent (no modal)."""
    profile_id = "e2e_list_delete"
    _create_profile(page, profile_id, "List Delete Me")
    try:
        agents = AgentsPage(page).goto()
        expect(agents.profiles.item(profile_id)).to_be_visible()

        agents.profiles.delete(profile_id)
        page.wait_for_timeout(500)

        profiles = page.request.get("/api/profiles?include_disabled=true").json()
        assert not any(p["id"] == profile_id for p in profiles)
    finally:
        _delete_profile(page, profile_id)


def test_duplicate_from_list(page: Page):
    """Duplicate on a list row creates a copy and keeps you on the list."""
    profile_id = "e2e_list_dup"
    _create_profile(page, profile_id, "List Dup Source")
    copy_id = None
    try:
        agents = AgentsPage(page).goto()
        agents.profiles.duplicate(profile_id)
        page.wait_for_timeout(500)

        # Still on the list, not in the editor.
        expect(page.get_by_test_id("agents-list")).to_be_visible()

        profiles = page.request.get("/api/profiles?include_disabled=true").json()
        copies = [p for p in profiles if "List Dup Source" in p["name"] and p["id"] != profile_id]
        assert len(copies) == 1
        copy_id = copies[0]["id"]
    finally:
        _delete_profile(page, profile_id)
        if copy_id:
            _delete_profile(page, copy_id)


def test_unsaved_guard_discard(page: Page):
    """Editing then leaving warns; Discard drops the edit and returns to the list."""
    profile_id = "e2e_guard_discard"
    _create_profile(page, profile_id, "Guard Discard")
    try:
        agents = AgentsPage(page).goto()
        agents.profiles.select(profile_id)

        agents.builder.name_input.fill("Edited But Discarded")
        agents.request_back()  # dirty -> the guard intercepts instead of navigating
        expect(agents.unsaved_dialog).to_be_visible()

        agents.discard_unsaved()
        expect(page.get_by_test_id("agents-list")).to_be_visible()

        # The edit was never saved.
        profile = page.request.get(f"/api/profiles/{profile_id}").json()
        assert profile["name"] == "Guard Discard"
    finally:
        _delete_profile(page, profile_id)


def test_unsaved_guard_keep_editing(page: Page):
    """Keep editing dismisses the guard and stays in the editor."""
    profile_id = "e2e_guard_keep"
    _create_profile(page, profile_id, "Guard Keep")
    try:
        agents = AgentsPage(page).goto()
        agents.profiles.select(profile_id)

        agents.builder.name_input.fill("Still Editing")
        agents.request_back()
        expect(agents.unsaved_dialog).to_be_visible()

        agents.keep_editing()
        expect(agents.unsaved_dialog).not_to_be_visible()
        expect(agents.builder.name_input).to_be_visible()
    finally:
        _delete_profile(page, profile_id)
