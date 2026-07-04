"""POM for the Agents view — the agent-profile list and its editor.

Agents live in the left-nav "Agents" panel: a searchable, sortable list
that opens the full profile editor with a back breadcrumb. 
The editor is the same ProfileBuilder component that used to
live under Settings, so its interaction surface is unchanged.
"""

from __future__ import annotations

from playwright.sync_api import Locator, Page

from tests.e2e.pages.settings_page import ModelPickerLocator


class ProfileList:
    """The agent list — search, and rows that open the editor."""

    def __init__(self, page: Page):
        self.page = page

    def item(self, profile_id: str) -> Locator:
        """The clickable list row for a profile."""
        return self.page.locator(f"[data-testid='profile-item-{profile_id}']")

    def select(self, profile_id: str) -> None:
        """Click a profile and wait for the editor to populate."""
        self.item(profile_id).click()
        self.page.locator("input[placeholder='Profile name']").wait_for(state="visible")

    def new(self) -> None:
        """Click 'New agent' and wait for the empty editor to render."""
        self.page.get_by_test_id("agents-new").click()
        self.page.locator("input[placeholder='Profile name']").wait_for(state="visible")

    def search(self, query: str) -> None:
        self.page.get_by_test_id("agents-search").fill(query)

    def _row(self, profile_id: str) -> Locator:
        return self.item(profile_id).locator("xpath=ancestor::tr")

    def delete(self, profile_id: str) -> None:
        """Inline two-click delete from the list row (no modal)."""
        btn = self._row(profile_id).get_by_test_id("agent-delete")
        btn.click()  # arm
        btn.click()  # confirm

    def duplicate(self, profile_id: str) -> None:
        """Inline duplicate from the list row."""
        self._row(profile_id).get_by_test_id("agent-duplicate").click()


class ProfileBuilder:
    """The profile editor — edit/save/delete the selected agent."""

    def __init__(self, page: Page):
        self.page = page

    # ── Inputs ────────────────────────────────────────────────────
    @property
    def name_input(self) -> Locator:
        return self.page.locator("input[placeholder='Profile name']")

    @property
    def description_input(self) -> Locator:
        return self.page.locator("input[placeholder='Short description']")

    @property
    def system_prompt(self) -> Locator:
        return self.page.locator("textarea[placeholder='System prompt...']")

    @property
    def model_picker(self) -> ModelPickerLocator:
        return ModelPickerLocator(self.page.get_by_test_id("profile-model-picker"))

    @property
    def enabled_toggle(self) -> Locator:
        return self.page.locator("[data-testid='profile-enabled-toggle'] input[type='checkbox']")

    @property
    def skill_chips(self) -> Locator:
        return self.page.locator("button[class*='chip']")

    def preset(self, label: str) -> Locator:
        return self.page.locator("[class*='presetBtn']", has_text=label)

    # ── Advanced section ──────────────────────────────────────────
    def open_advanced(self) -> "ProfileBuilder":
        self.page.get_by_text("Advanced Settings").click()
        return self

    def field(self, name: str) -> Locator:
        """Advanced inference field by name (e.g. 'temperature', 'top_k')."""
        return self.page.get_by_test_id(f"field-{name}")

    def auto_field(self, idx: int) -> Locator:
        """Inference fields with placeholder='auto' (temperature, top_k, top_p,
        repeat_penalty, context_window — in that source order)."""
        return self.page.locator("input[placeholder='auto']").nth(idx)

    def unlimited_field(self, idx: int) -> Locator:
        """Fields with placeholder='unlimited' (num_predict, max_iterations)."""
        return self.page.locator("input[placeholder='unlimited']").nth(idx)

    @property
    def thinking_switch(self) -> Locator:
        return self.page.get_by_role("switch", name="Thinking")

    # ── Action bar ────────────────────────────────────────────────
    def save(self) -> "ProfileBuilder":
        self.page.get_by_role("button", name="Save").click()
        return self

    def duplicate(self) -> "ProfileBuilder":
        self.page.get_by_role("button", name="Duplicate").click()
        return self

    def delete(self) -> "ProfileBuilder":
        # ConfirmButton: first click arms ("Confirm?"), second click fires.
        self.page.get_by_role("button", name="Delete", exact=True).click()
        self.page.get_by_role("button", name="Confirm?").click()
        return self

    # ── Inline feedback ───────────────────────────────────────────
    @property
    def save_error(self) -> Locator:
        return self.page.locator("[data-testid='profile-save-error']")

    @property
    def delete_conflict(self) -> Locator:
        return self.page.locator("[data-testid='profile-delete-conflict']")

    def dismiss_delete_conflict(self) -> "ProfileBuilder":
        self.delete_conflict.get_by_role("button", name="Dismiss").click()
        return self


class AgentsPage:
    """Agents view — left-nav entry, list, and profile editor."""

    def __init__(self, page: Page):
        self.page = page
        self.profiles = ProfileList(page)
        self.builder = ProfileBuilder(page)

    def goto(self) -> "AgentsPage":
        """Open the Agents view from the left nav (lands on the list)."""
        self.page.goto("/")
        self.page.get_by_role("button", name="Agents", exact=True).click()
        self.page.get_by_test_id("agents-list").wait_for(state="visible")
        return self

    def back(self) -> "AgentsPage":
        """Return from the editor to the list via the back breadcrumb.

        Assumes no unsaved edits — with edits the guard intercepts and the
        list never appears; use ``request_back`` for that case.
        """
        self.page.get_by_test_id("agent-detail-back").click()
        self.page.get_by_test_id("agents-list").wait_for(state="visible")
        return self

    def request_back(self) -> "AgentsPage":
        """Click the back breadcrumb without asserting the destination — with
        unsaved edits this surfaces the guard instead of leaving."""
        self.page.get_by_test_id("agent-detail-back").click()
        return self

    # ── Unsaved-changes guard (shown on back-out with edits) ──────
    @property
    def unsaved_dialog(self) -> Locator:
        return self.page.get_by_test_id("agent-unsaved-warning")

    def discard_unsaved(self) -> "AgentsPage":
        self.page.get_by_test_id("agent-unsaved-discard").click()
        self.page.get_by_test_id("agents-list").wait_for(state="visible")
        return self

    def keep_editing(self) -> "AgentsPage":
        self.page.get_by_test_id("agent-unsaved-keep").click()
        return self

    def close(self) -> "AgentsPage":
        """Toggle the Agents nav entry to leave the view and return to chat."""
        self.page.get_by_role("button", name="Agents", exact=True).click()
        return self
