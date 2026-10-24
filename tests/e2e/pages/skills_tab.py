"""POM for the Settings → Skills library and shared tool selection editor."""

from __future__ import annotations

from playwright.sync_api import Locator, Page
from tests.e2e.pages.tool_selection import ToolSelection


class SkillsTab:
    def __init__(self, page: Page):
        self.page = page
        self.tools = ToolSelection(page)

    def search(self, text: str) -> "SkillsTab":
        self.page.get_by_role("searchbox").fill(text)
        return self

    # ── My Skills list ────────────────────────────────────────────
    def item(self, skill_id: str) -> Locator:
        return self.page.get_by_test_id(f"skill-item-{skill_id}")

    def select(self, skill_id: str) -> "SkillsTab":
        self.item(skill_id).click()
        self.name_input.wait_for(state="visible")
        return self

    def new(self) -> "SkillsTab":
        self.page.get_by_role("button", name="+ New").click()
        self.name_input.wait_for(state="visible")
        return self

    def export_row(self, skill_id: str) -> None:
        """Click the row's export button (triggers a download)."""
        self.item(skill_id).get_by_test_id(f"skill-export-{skill_id}").click()

    def export_editor(self) -> None:
        """Click the editor's Export button (triggers a download)."""
        self.page.get_by_test_id("skill-export").click()

    def import_file(self, path: str) -> "SkillsTab":
        """Feed a pack file to the hidden import input (no OS dialog)."""
        self.page.get_by_test_id("skills-import-input").set_input_files(path)
        return self

    # ── Skill editor ──────────────────────────────────────────────
    @property
    def name_input(self) -> Locator:
        return self.page.get_by_test_id("skill-name-input")

    @property
    def description_input(self) -> Locator:
        return self.page.get_by_test_id("skill-desc-input")

    @property
    def prompt(self) -> Locator:
        return self.page.get_by_test_id("skill-prompt")

    def save(self) -> "SkillsTab":
        self.page.get_by_role("button", name="Save", exact=True).click()
        return self

    def revert(self) -> "SkillsTab":
        self.page.get_by_role("button", name="Revert").click()
        return self

    def delete(self) -> "SkillsTab":
        # ConfirmButton: first click arms ("Confirm?"), second fires.
        self.page.get_by_role("button", name="Delete", exact=True).click()
        self.page.get_by_role("button", name="Confirm?").click()
        return self

    @property
    def save_error(self) -> Locator:
        return self.page.get_by_test_id("skill-save-error")
