"""POM for the browser takeover control plane inside its stable view."""

from __future__ import annotations

from playwright.sync_api import Locator, Page


class BrowserControl:
    def __init__(self, page: Page, root_testid: str = "browser-preview"):
        self.page = page
        self._root_id = root_testid

    @property
    def root(self) -> Locator:
        return self.page.get_by_test_id(self._root_id)

    # ── elements ────────────────────────────────────────────────────
    @property
    def view(self) -> Locator:
        return self.root.get_by_test_id("browser-viewport")

    @property
    def frame(self) -> Locator:
        return self.root.get_by_test_id("browser-frame")

    @property
    def address(self) -> Locator:
        return self.root.get_by_test_id("browser-address")

    @property
    def page_title(self) -> Locator:
        return self.root.get_by_test_id("browser-page-title")

    @property
    def take_control_btn(self) -> Locator:
        return self.root.get_by_test_id("browser-take-control")

    @property
    def new_tab_btn(self) -> Locator:
        return self.root.get_by_test_id("browser-new-tab")

    @property
    def fullscreen_btn(self) -> Locator:
        host = self.root.locator("xpath=ancestor::*[@data-view-id][1]")
        tab_group_id = host.get_attribute("data-tab-group-id")
        tab_bar = self.page.get_by_test_id(
            f"desktop-tab-group-{tab_group_id}-tab-bar"
        )
        tab_bar.locator("[data-testid^='view-tab-actions-']").click()
        return self.page.locator("[data-testid^='maximize-view-']")

    @property
    def tab_rail(self) -> Locator:
        return self.root.get_by_test_id("browser-tab-rail")

    @property
    def tabs(self) -> Locator:
        """Tab cards in the rail (only present when >1 tab is open)."""
        return self.tab_rail.get_by_role("tab")

    def tab(self, tab_id: int) -> Locator:
        return self.root.get_by_test_id(f"browser-tab-{tab_id}")

    def tab_close(self, tab_id: int) -> Locator:
        return self.root.get_by_test_id(f"browser-tab-close-{tab_id}")

    def nav_btn(self, direction: str) -> Locator:
        return self.root.get_by_test_id(f"browser-nav-{direction}")

    # ── actions ─────────────────────────────────────────────────────
    def wait_loaded(self, timeout: int = 15_000) -> "BrowserControl":
        """Wait until the screencast frame is showing (browser launched)."""
        self.frame.wait_for(state="visible", timeout=timeout)
        return self

    def take_control(self, timeout: int = 5_000) -> "BrowserControl":
        """Engage takeover; confirmed by the address input appearing."""
        self.take_control_btn.click()
        self.address.wait_for(state="visible", timeout=timeout)
        return self

    def is_engaged(self) -> bool:
        return self.address.is_visible()

    def goto(self, url: str) -> "BrowserControl":
        self.address.click()
        self.address.fill(url)
        self.address.press("Enter")
        return self

    def click_view(self) -> "BrowserControl":
        """Forward a click at the view centre to the remote page."""
        self.view.click()
        return self

    def type_text(self, text: str) -> "BrowserControl":
        """Focus the view and forward each character to the remote page."""
        self.view.click()
        self.page.keyboard.type(text)
        return self

    def press(self, key: str) -> "BrowserControl":
        self.view.focus()
        self.page.keyboard.press(key)
        return self

    def scroll(self, dy: int = 600) -> "BrowserControl":
        self.view.hover()
        self.page.mouse.wheel(0, dy)
        return self
