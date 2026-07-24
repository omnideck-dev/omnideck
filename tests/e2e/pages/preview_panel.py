"""POM for workspace surfaces hosted in the desktop's right pane."""

from __future__ import annotations

from playwright.sync_api import Locator, Page

from .file_preview import FilePreview


class PreviewPanel:
    """Workspace-preview conveniences over the generic right pane."""

    def __init__(self, page: Page):
        self.page = page
        self.file = FilePreview(page)

    @property
    def root(self) -> Locator:
        return self.page.get_by_test_id("desktop-pane-right")

    @property
    def split_handle(self) -> Locator:
        return self.page.locator("[role='separator']")

    @property
    def tab_bar(self) -> Locator:
        return self.page.get_by_test_id("desktop-pane-right-tab-bar")

    @property
    def tabs(self) -> Locator:
        return self.tab_bar.locator("[data-testid^='surface-tab-']")

    @property
    def terminal_tab(self) -> Locator:
        return self.page.get_by_test_id("surface-tab-terminal")

    @property
    def browser_tab(self) -> Locator:
        return self.page.get_by_test_id("surface-tab-browser")

    @property
    def file_tabs(self) -> Locator:
        """All file tabs across the panel."""
        return self.page.locator("[data-testid^='surface-tab-file:']")

    def file_tab(self, filename: str) -> Locator:
        return self.page.locator(f"[data-testid='surface-tab-file:{filename}']")

    @property
    def content(self) -> Locator:
        return self.page.locator(
            "[data-surface-id][data-pane-id='right'][data-active='true']"
        )

    def select_tab(self, tab: Locator) -> "PreviewPanel":
        tab.click()
        self.page.wait_for_timeout(200)
        return self

    def close_first_tab(self) -> "PreviewPanel":
        self.tab_bar.locator("[data-testid^='close-surface-tab-']").first.click()
        self.page.wait_for_timeout(200)
        return self

    def close_all_tabs(self) -> "PreviewPanel":
        while self.tabs.count() > 0:
            self.close_first_tab()
        return self

    def open_file_tab_by_extension(self, ext: str) -> str | None:
        """Click the first file tab whose name ends with ext. Returns filename or None."""
        tabs = self.file_tabs
        for i in range(tabs.count()):
            testid = tabs.nth(i).get_attribute("data-testid") or ""
            filename = testid.replace("surface-tab-file:", "")
            if filename.endswith(ext):
                tabs.nth(i).click()
                self.page.wait_for_timeout(200)
                return filename
        return None
