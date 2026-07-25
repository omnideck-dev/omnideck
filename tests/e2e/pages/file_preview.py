"""POM for inline file-preview controls inside an active desktop view."""

from __future__ import annotations

from playwright.sync_api import Locator, Page


class FilePreview:
    """Controls inside an active file view."""

    def __init__(self, page: Page):
        self.page = page

    @property
    def content(self) -> Locator:
        return self.page.locator(
            "[data-view-type='artifact-file'][data-visible='true']"
        )

    @property
    def editor(self) -> Locator:
        """The CodeMirror editable view shown in source mode."""
        return self.content.locator(".cm-content")

    @property
    def save_button(self) -> Locator:
        return self.content.get_by_test_id("file-save")

    def set_source(self, text: str) -> "FilePreview":
        """Replace the whole editor buffer with text (source mode)."""
        self.editor.click()
        self.page.keyboard.press("Control+a")
        self.page.keyboard.press("Delete")
        self.page.keyboard.type(text)
        self.page.wait_for_timeout(150)
        return self

    def save(self) -> "FilePreview":
        self.save_button.click()
        self.page.wait_for_timeout(300)
        return self

    @property
    def toggle(self) -> Locator:
        return self.content.get_by_test_id("file-view-toggle")

    @property
    def source_only(self) -> Locator:
        return self.content.get_by_test_id("file-view-source-only")

    def view_source(self) -> "FilePreview":
        self.content.get_by_test_id("file-view-source").click()
        self.page.wait_for_timeout(200)
        return self

    def view_preview(self) -> "FilePreview":
        self.content.get_by_test_id("file-view-preview").click()
        self.page.wait_for_timeout(200)
        return self

    def open_fullscreen(self) -> "FullscreenPreview":
        from .fullscreen_preview import FullscreenPreview

        view_id = self.content.get_attribute("data-view-id")
        assert view_id
        host = self.page.locator(f'[data-view-id="{view_id}"]')
        tab_group_id = host.get_attribute("data-tab-group-id")
        if tab_group_id == "floating":
            host.locator("[data-testid^='maximize-view-']").click()
        else:
            tab_bar = self.page.get_by_test_id(
                f"desktop-tab-group-{tab_group_id}-tab-bar"
            )
            tab_bar.locator(
                "[data-testid^='view-tab-actions-']"
            ).click()
            self.page.locator(
                "[data-testid^='maximize-view-']"
            ).click()
        self.page.wait_for_timeout(300)
        return FullscreenPreview(self.page)

    def download_button(self) -> Locator:
        return self.content.get_by_test_id("file-download")
