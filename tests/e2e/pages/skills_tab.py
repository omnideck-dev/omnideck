"""POM for the Settings → Skills tab.

Covers the two views the Library Header switches between: My Skills (a
master-detail list + editor) and Tool Categories (the read-only catalog).
"""

from __future__ import annotations

from playwright.sync_api import Locator, Page


class SkillsTab:
    def __init__(self, page: Page):
        self.page = page

    # ── Library Header: view switch + scoped search ───────────────
    @property
    def my_skills_tab(self) -> Locator:
        return self.page.get_by_role("tab", name="My Skills")

    @property
    def categories_tab(self) -> Locator:
        return self.page.get_by_role("tab", name="Tool Categories")

    def view_my_skills(self) -> "SkillsTab":
        self.my_skills_tab.click()
        return self

    def view_categories(self) -> "SkillsTab":
        self.categories_tab.click()
        return self

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

    def category_chip(self, category_id: str) -> Locator:
        return self.page.get_by_test_id(f"cat-chip-{category_id}")

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

    # ── Tool Categories catalog ───────────────────────────────────
    def category_row(self, category_id: str) -> Locator:
        return self.page.get_by_test_id(f"cat-row-{category_id}")

    def category_tools(self, category_id: str) -> Locator:
        return self.page.get_by_test_id(f"cat-tools-{category_id}")
