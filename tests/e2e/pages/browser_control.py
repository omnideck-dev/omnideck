"""POM for the browser takeover control plane — the shared chrome bar + the
screencast surface, used by both the inline preview and the fullscreen view.

Selectors are scoped to a root container (``browser-preview`` inline,
``fullscreen-preview`` for fullscreen) so the same semantic test ids work in
either context and survive a future component refactor.
"""

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
    def surface(self) -> Locator:
        return self.root.get_by_test_id("browser-surface")

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
        return self.root.get_by_test_id("browser-fullscreen")

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

    def click_surface(self) -> "BrowserControl":
        """Forward a click at the surface centre to the remote page."""
        self.surface.click()
        return self

    def type_text(self, text: str) -> "BrowserControl":
        """Focus the surface and forward each character to the remote page."""
        self.surface.click()
        self.page.keyboard.type(text)
        return self

    def press(self, key: str) -> "BrowserControl":
        self.surface.focus()
        self.page.keyboard.press(key)
        return self

    def scroll(self, dy: int = 600) -> "BrowserControl":
        self.surface.hover()
        self.page.mouse.wheel(0, dy)
        return self
