"""POM for inline file-preview controls inside an active desktop surface."""

from __future__ import annotations

from playwright.sync_api import Locator, Page


class FilePreview:
    """Controls inside an active file surface."""

    def __init__(self, page: Page):
        self.page = page

    @property
    def content(self) -> Locator:
        return self.page.locator(
            "[data-surface-id][data-pane-id='right'][data-active='true']"
        )

    @property
    def editor(self) -> Locator:
        """The CodeMirror editable surface shown in source mode."""
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

        pane_id = self.content.get_attribute("data-pane-id")
        self.page.get_by_test_id(
            f"desktop-pane-{pane_id}-tab-bar"
        ).locator("[data-testid^='maximize-surface-']").click()
        self.page.wait_for_timeout(300)
        return FullscreenPreview(self.page)

    def download_button(self) -> Locator:
        return self.content.get_by_test_id("file-download")
