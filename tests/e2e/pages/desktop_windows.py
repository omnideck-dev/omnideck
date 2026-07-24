"""POM for the generic tab, split, floating, and full-screen desktop."""

from __future__ import annotations

from playwright.sync_api import Locator, Page


class DesktopWindows:
    """User-facing placement controls owned by the desktop window manager."""

    def __init__(self, page: Page):
        self.page = page

    @property
    def root(self) -> Locator:
        return self.page.get_by_test_id("desktop-window-layout")

    @property
    def split_handle(self) -> Locator:
        return self.page.get_by_role("separator", name="Resize panes")

    def pane(self, pane_id: str) -> Locator:
        return self.page.get_by_test_id(f"desktop-pane-{pane_id}")

    def tab_bar(self, pane_id: str) -> Locator:
        return self.page.get_by_test_id(f"desktop-pane-{pane_id}-tab-bar")

    def tab_list(self, pane_id: str) -> Locator:
        return self.tab_bar(pane_id).locator("[class*='tabList']")

    def tabs(self, pane_id: str) -> Locator:
        return self.tab_bar(pane_id).locator("[data-testid^='surface-tab-']")

    def tab(self, surface_key: str) -> Locator:
        return self.page.get_by_test_id(f"surface-tab-{surface_key}")

    def surface(self, surface_id: str) -> Locator:
        return self.page.locator(f'[data-surface-id="{surface_id}"]')

    def active_surface(self, pane_id: str) -> Locator:
        return self.page.locator(
            f'[data-pane-id="{pane_id}"][data-active="true"]'
        )

    def open_tab_menu(self, surface_key: str) -> Locator:
        self.tab(surface_key).click(button="right")
        menu = self.page.get_by_test_id(f"surface-tab-menu-{surface_key}")
        menu.wait_for(state="visible")
        return menu

    def choose_tab_action(self, surface_key: str, action_id: str) -> None:
        menu = self.open_tab_menu(surface_key)
        menu.get_by_test_id(f"tab-context-action-{action_id}").click()

    def move(self, surface_key: str, pane_id: str) -> None:
        self.page.get_by_test_id(
            f"move-surface-{surface_key}-{pane_id}"
        ).click()

    def float(self, surface_key: str) -> None:
        self.page.get_by_test_id(f"float-surface-{surface_key}").click()

    def maximize(self, surface_key: str) -> None:
        self.page.get_by_test_id(f"maximize-surface-{surface_key}").click()

    def restore(self, surface_key: str) -> None:
        self.page.get_by_test_id(f"restore-surface-{surface_key}").click()

    def floating_header(self, surface_key: str) -> Locator:
        return self.page.get_by_test_id(f"floating-surface-header-{surface_key}")

    def drag_floating_window(
        self,
        surface_key: str,
        *,
        target_x: float,
        target_y: float,
    ) -> None:
        header = self.floating_header(surface_key)
        box = header.bounding_box()
        assert box, f"{surface_key} floating header has no bounds"
        self.page.mouse.move(box["x"] + 60, box["y"] + box["height"] / 2)
        self.page.mouse.down()
        self.page.mouse.move(target_x, target_y, steps=8)
        self.page.mouse.up()

    def resize_floating_window(
        self,
        surface_id: str,
        *,
        delta_x: float,
        delta_y: float,
    ) -> None:
        window = self.surface(surface_id)
        box = window.bounding_box()
        assert box, f"{surface_id} floating window has no bounds"
        self.page.mouse.move(box["x"] + box["width"] - 2, box["y"] + box["height"] - 2)
        self.page.mouse.down()
        self.page.mouse.move(
            box["x"] + box["width"] + delta_x,
            box["y"] + box["height"] + delta_y,
            steps=8,
        )
        self.page.mouse.up()
