"""POM for the Settings page — Skills / Providers / Integrations / Memory / System tabs.

Agent profiles moved out of Settings into their own left-nav view.
"""

from __future__ import annotations

from playwright.sync_api import Locator, Page

from tests.e2e.pages.integrations_tab import IntegrationsTab
from tests.e2e.pages.skills_tab import SkillsTab


class ModelPickerLocator:
    """Interaction helper for the ModelPicker component.

    The picker is a chip trigger that opens a popover on click. The
    closed-state value is exposed via ``data-selected-model`` on the
    trigger button so it can be read without opening.

    Inline pickers portal the popover to ``document.body``, so popover
    and item lookups go through the page, not the wrapper root.
    """

    def __init__(self, root: Locator):
        self._root = root
        self._page = root.page
        self.trigger = root.get_by_test_id("model-picker-trigger")

    def selected_value(self) -> str:
        return self.trigger.get_attribute("data-selected-model") or ""

    def open(self) -> None:
        """Open the popover if it isn't already open."""
        if self.trigger.get_attribute("aria-expanded") != "true":
            self.trigger.click()
        # Wait for the popover to be visible.
        self._page.get_by_test_id("model-picker-popover").wait_for(state="visible", timeout=5_000)

    def items(self) -> Locator:
        return self._page.get_by_test_id("model-item")

    def select(self, model_name: str) -> None:
        self.open()
        self._page.locator(f"[data-model-name='{model_name}']").click()

    def select_different(self, current: str) -> str:
        """Open and pick the first model whose name differs from *current*."""
        self.open()
        items = self.items()
        items.first.wait_for(state="visible", timeout=10_000)
        for i in range(items.count()):
            name = items.nth(i).get_attribute("data-model-name")
            if name != current:
                items.nth(i).click()
                return name
        raise AssertionError("No alternative model found")


class SystemTab:
    """The System tab inside Settings."""

    def __init__(self, page: Page):
        self.page = page

    @property
    def default_agent_select(self) -> Locator:
        return self.page.locator("select").first

    @property
    def vision_model_picker(self) -> ModelPickerLocator:
        return ModelPickerLocator(self.page.get_by_test_id("vision-model-picker"))

    @property
    def compaction_model_picker(self) -> ModelPickerLocator:
        return ModelPickerLocator(self.page.get_by_test_id("compaction-model-picker"))

    def open_vision_advanced(self) -> "SystemTab":
        self.page.get_by_test_id("vision-advanced-toggle").click()
        self.page.get_by_test_id("vision-advanced-panel").wait_for(state="visible")
        return self

    @property
    def vision_think_toggle(self) -> Locator:
        return self.page.get_by_test_id("vision-think-toggle")

    def vision_option(self, key: str) -> Locator:
        return self.page.get_by_test_id(f"vision-option-{key}")


class SettingsPage:
    """Settings page — sidebar entry + Skills / Providers / System / … tabs."""

    def __init__(self, page: Page):
        self.page = page
        self.system = SystemTab(page)
        self.integrations = IntegrationsTab(page)
        self.skills = SkillsTab(page)

    def goto(self) -> "SettingsPage":
        """Open Settings (lands on the Skills tab, the default)."""
        self.page.goto("/")
        self.page.get_by_test_id("sidebar-settings").click()
        self.page.get_by_test_id("settings-tab-skills").wait_for(state="visible")
        return self

    def goto_system(self) -> "SettingsPage":
        """Open Settings and switch to the System tab."""
        self.goto()
        self.page.get_by_test_id("settings-tab-system").click()
        self.page.locator("[class*='settingRow']").first.wait_for(state="visible")
        return self

    def goto_integrations(self) -> "SettingsPage":
        """Open Settings and switch to the Integrations tab."""
        self.goto()
        self.page.get_by_test_id("settings-tab-integrations").click()
        return self

    def goto_providers(self) -> "SettingsPage":
        """Open Settings and switch to the Providers tab."""
        self.goto()
        self.page.get_by_test_id("settings-tab-providers").click()
        self.page.get_by_test_id("providers-tab").wait_for(state="visible")
        return self

    def goto_memory(self) -> "SettingsPage":
        """Open Settings and switch to the Memory tab."""
        self.goto()
        self.page.get_by_test_id("settings-tab-memory").click()
        self.page.get_by_test_id("memory-tab").wait_for(state="visible")
        return self

    def goto_skills(self) -> "SettingsPage":
        """Open Settings and switch to the Skills tab."""
        self.goto()
        self.page.get_by_test_id("settings-tab-skills").click()
        self.page.get_by_test_id("skills-tab").wait_for(state="visible")
        return self

    def close(self) -> "SettingsPage":
        """Toggle the Settings sidebar entry to leave the Settings view."""
        self.page.get_by_test_id("sidebar-settings").click()
        return self
