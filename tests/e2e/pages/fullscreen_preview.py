"""POM for a surface maximized by the desktop window manager."""

from __future__ import annotations

from playwright.sync_api import Locator, Page


class FullscreenPreview:
    """A stable surface host promoted over the split layout."""

    def __init__(self, page: Page):
        self.page = page

    @property
    def root(self) -> Locator:
        return self.page.locator("[data-surface-id][data-maximized='true']")

    def close_with_escape(self) -> None:
        self.page.keyboard.press("Escape")
        self.page.wait_for_timeout(300)

    def back(self) -> None:
        self.root.locator("[data-testid^='restore-surface-']").click()
        self.page.wait_for_timeout(300)
