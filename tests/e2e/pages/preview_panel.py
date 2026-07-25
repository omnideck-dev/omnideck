"""POM for Browser, Terminal, and artifact views in the desktop."""

from __future__ import annotations

from playwright.sync_api import Locator, Page

from .file_preview import FilePreview


class PreviewTabGroup:
    """Workspace-resource and artifact conveniences over the generic desktop."""

    def __init__(self, page: Page):
        self.page = page
        self.file = FilePreview(page)

    @property
    def root(self) -> Locator:
        return self.page.get_by_test_id("desktop-tab-group-right")

    @property
    def split_handle(self) -> Locator:
        return self.page.locator("[role='separator']")

    @property
    def tab_bar(self) -> Locator:
        return self.page.get_by_test_id("desktop-tab-group-right-tab-bar")

    @property
    def tabs(self) -> Locator:
        return self.tab_bar.get_by_role("tab")

    @property
    def terminal_tab(self) -> Locator:
        return self.page.get_by_test_id("view-tab-terminal")

    @property
    def browser_tab(self) -> Locator:
        return self.page.get_by_test_id("view-tab-browser")

    @property
    def file_tabs(self) -> Locator:
        """All artifact file tabs across both tab groups."""
        return self.page.locator(
            "[role='tab'][data-testid^='view-tab-artifact:']"
        )

    def file_tab(self, filename: str) -> Locator:
        return self.page.get_by_test_id(f"view-tab-artifact:{filename}")

    @property
    def content(self) -> Locator:
        return self.page.locator(
            "[data-view-id][data-tab-group-id='right'][data-active='true']"
        )

    def select_tab(self, tab: Locator) -> "PreviewTabGroup":
        tab.click()
        self.page.wait_for_timeout(200)
        return self

    def close_first_tab(self) -> "PreviewTabGroup":
        tab = self.tabs.first
        view_key = (
            tab.get_attribute("data-testid") or ""
        ).removeprefix("view-tab-")
        tab.click(button="right")
        self.page.get_by_test_id(
            f"view-tab-menu-{view_key}"
        ).get_by_test_id("tab-context-action-close").click()
        self.page.wait_for_timeout(200)
        return self

    def close_all_tabs(self) -> "PreviewTabGroup":
        while self.tabs.count() > 0:
            self.close_first_tab()
        return self

    def open_file_tab_by_extension(self, ext: str) -> str | None:
        """Click the first file tab whose name ends with ext. Returns filename or None."""
        tabs = self.file_tabs
        for i in range(tabs.count()):
            testid = tabs.nth(i).get_attribute("data-testid") or ""
            filename = testid.replace("view-tab-artifact:", "")
            if filename.endswith(ext):
                tabs.nth(i).click()
                self.page.wait_for_timeout(200)
                return filename
        return None
