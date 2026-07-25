"""POM for the generic tab, split, floating, and full-screen desktop."""

from __future__ import annotations

from playwright.sync_api import Locator, Page


class DesktopLayout:
    """User-facing placement controls owned by Desktop Layout."""

    def __init__(self, page: Page):
        self.page = page

    @property
    def root(self) -> Locator:
        return self.page.get_by_test_id("desktop-layout")

    @property
    def split_handle(self) -> Locator:
        return self.page.get_by_role("separator", name="Resize tab groups")

    def tab_group(self, tab_group_id: str) -> Locator:
        return self.page.get_by_test_id(f"desktop-tab-group-{tab_group_id}")

    def tab_bar(self, tab_group_id: str) -> Locator:
        return self.page.get_by_test_id(
            f"desktop-tab-group-{tab_group_id}-tab-bar"
        )

    def tab_list(self, tab_group_id: str) -> Locator:
        return self.tab_bar(tab_group_id).locator("[class*='tabList']")

    def tabs(self, tab_group_id: str) -> Locator:
        return self.tab_bar(tab_group_id).get_by_role("tab")

    def tab(self, view_key: str) -> Locator:
        return self.page.get_by_test_id(f"view-tab-{view_key}")

    def view(self, view_id: str) -> Locator:
        return self.page.locator(f'[data-view-id="{view_id}"]')

    def active_view(self, tab_group_id: str) -> Locator:
        return self.page.locator(
            f'[data-tab-group-id="{tab_group_id}"][data-active="true"]'
        )

    def open_tab_menu(self, view_key: str) -> Locator:
        self.tab(view_key).click(button="right")
        menu = self.page.get_by_test_id(f"view-tab-menu-{view_key}")
        menu.wait_for(state="visible")
        return menu

    def open_tab_actions(self, view_key: str) -> Locator:
        """Open the visible overflow menu for the currently active tab."""
        self.page.get_by_test_id(f"view-tab-actions-{view_key}").click()
        menu = self.page.get_by_test_id(f"view-tab-menu-{view_key}")
        menu.wait_for(state="visible")
        return menu

    def choose_tab_action(self, view_key: str, action_id: str) -> None:
        menu = self.open_tab_menu(view_key)
        menu.get_by_test_id(f"tab-context-action-{action_id}").click()

    def move(self, view_key: str, tab_group_id: str) -> None:
        self.open_tab_actions(view_key)
        self.page.get_by_test_id(
            f"move-view-{view_key}-{tab_group_id}"
        ).click()

    def float(self, view_key: str) -> None:
        self.open_tab_actions(view_key)
        self.page.get_by_test_id(f"float-view-{view_key}").click()

    def maximize(self, view_key: str) -> None:
        maximize = self.page.get_by_test_id(f"maximize-view-{view_key}")
        # Floating chrome exposes placement actions directly, while docked
        # tabs keep them in the overflow menu. Support both presentations so
        # callers describe the intent rather than the current chrome.
        if maximize.is_visible():
            maximize.click()
            return
        self.open_tab_actions(view_key)
        maximize.click()

    def restore(self, view_key: str) -> None:
        self.page.get_by_test_id(f"restore-view-{view_key}").click()

    def floating_header(self, view_key: str) -> Locator:
        return self.page.get_by_test_id(f"floating-view-header-{view_key}")

    def drag_floating_view(
        self,
        view_key: str,
        *,
        target_x: float,
        target_y: float,
    ) -> None:
        header = self.floating_header(view_key)
        box = header.bounding_box()
        assert box, f"{view_key} floating header has no bounds"
        self.page.mouse.move(box["x"] + 60, box["y"] + box["height"] / 2)
        self.page.mouse.down()
        self.page.mouse.move(target_x, target_y, steps=8)
        self.page.mouse.up()

    def resize_floating_view(
        self,
        view_id: str,
        *,
        delta_x: float,
        delta_y: float,
    ) -> None:
        view = self.view(view_id)
        box = view.bounding_box()
        assert box, f"{view_id} floating view has no bounds"
        self.page.mouse.move(box["x"] + box["width"] - 2, box["y"] + box["height"] - 2)
        self.page.mouse.down()
        self.page.mouse.move(
            box["x"] + box["width"] + delta_x,
            box["y"] + box["height"] + delta_y,
            steps=8,
        )
        self.page.mouse.up()
