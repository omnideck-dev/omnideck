"""E2E coverage for the generic desktop layout manager."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from tests.e2e.pages import ChatView, DesktopLayout


def _open_destinations(page: Page, *destinations: str) -> None:
    for destination in destinations:
        if destination == "settings":
            page.get_by_test_id("sidebar-settings").click()
        else:
            page.get_by_test_id(f"sidebar-nav-{destination}").click()


def _rect(locator):
    box = locator.bounding_box()
    assert box
    return box


def test_navigation_destinations_are_retained_as_tabs(page: Page):
    """Opening pages retains earlier pages in the same tab stack."""
    ChatView(page).goto()
    desktop = DesktopLayout(page)
    _open_destinations(page, "agents", "routines", "artifacts", "settings")

    for view_key in (
        "destination:conversation",
        "destination:agents",
        "destination:routines",
        "destination:artifacts",
        "destination:settings",
    ):
        expect(desktop.tab(view_key)).to_be_visible()

    expect(desktop.active_view("left")).to_have_attribute(
        "data-view-id", "destination:settings"
    )
    desktop.tab("destination:agents").click()
    expect(page.get_by_test_id("agents-view")).to_be_visible()
    expect(desktop.view("destination:settings")).not_to_be_visible()
    expect(desktop.tab("destination:settings")).to_be_visible()


def test_inactive_tab_context_menu_controls_that_tab(page: Page):
    """Right-click actions target an inactive tab without selecting it first."""
    ChatView(page).goto()
    desktop = DesktopLayout(page)
    _open_destinations(page, "agents", "routines", "artifacts")
    expect(desktop.active_view("left")).to_have_attribute(
        "data-view-id", "destination:artifacts"
    )

    desktop.choose_tab_action("destination:agents", "move")
    expect(desktop.view("destination:agents")).to_have_attribute(
        "data-tab-group-id", "right"
    )
    expect(desktop.active_view("left")).to_have_attribute(
        "data-view-id", "destination:artifacts"
    )

    desktop.choose_tab_action("destination:routines", "close-right")
    expect(desktop.tab("destination:artifacts")).to_have_count(0)
    expect(desktop.tab("destination:routines")).to_be_visible()

    desktop.choose_tab_action("destination:routines", "close-others")
    expect(desktop.tabs("left")).to_have_count(1)
    expect(desktop.tab("destination:routines")).to_be_visible()


def test_overflow_controls_scroll_and_reveal_the_selected_tab(page: Page):
    """A crowded tab strip remains navigable and keeps selection in view."""
    page.set_viewport_size({"width": 720, "height": 720})
    ChatView(page).goto()
    desktop = DesktopLayout(page)
    _open_destinations(page, "agents", "routines", "artifacts", "settings")

    left_scroll = page.get_by_test_id("desktop-tab-group-left-tab-bar-scroll-left")
    right_scroll = page.get_by_test_id("desktop-tab-group-left-tab-bar-scroll-right")
    expect(left_scroll).to_be_visible()
    expect(right_scroll).to_be_visible()

    tab_list = desktop.tab_list("left")
    right_scroll.click()
    page.wait_for_timeout(300)
    scrolled_right = tab_list.evaluate("element => element.scrollLeft")
    assert scrolled_right > 0
    left_scroll.click()
    page.wait_for_timeout(300)
    assert tab_list.evaluate("element => element.scrollLeft") < scrolled_right

    # Scroll away again, then select an off-screen tab without Playwright
    # helpfully scrolling it first. The tab component itself must reveal it.
    right_scroll.click()
    page.wait_for_timeout(300)
    desktop.tab("destination:conversation").evaluate("element => element.click()")
    page.wait_for_timeout(300)

    list_box = _rect(tab_list)
    tab_box = _rect(desktop.tab("destination:conversation"))
    assert tab_box["x"] >= list_box["x"] - 1
    assert tab_box["x"] + tab_box["width"] <= list_box["x"] + list_box["width"] + 1


def test_split_resize_tab_order_and_selection_persist_on_refresh(page: Page):
    """Docked layout, order, selection, and the dragged split survive reload."""
    ChatView(page).goto()
    desktop = DesktopLayout(page)
    _open_destinations(page, "settings")
    desktop.move("destination:settings", "right")
    _open_destinations(page, "agents")
    expect(desktop.active_view("left")).to_have_attribute(
        "data-view-id", "destination:agents"
    )

    handle_box = _rect(desktop.split_handle)
    before = desktop.root.get_attribute("style")
    page.mouse.move(
        handle_box["x"] + handle_box["width"] / 2,
        handle_box["y"] + 100,
    )
    page.mouse.down()
    page.mouse.move(handle_box["x"] + 150, handle_box["y"] + 100, steps=8)
    page.mouse.up()
    page.wait_for_timeout(300)
    resized = desktop.root.get_attribute("style")
    assert resized != before
    # Pin the persisted bytes as well as the restored UI. A later bootstrap
    # command must not be able to hide a stale snapshot write by changing the
    # selection only after reload.
    saved_active_view_id = page.evaluate(
        """() => JSON.parse(
            localStorage.getItem('omnideck_desktop_window_v1')
        ).layout.tabGroups.left.activeViewId"""
    )
    assert saved_active_view_id == "destination:agents"

    page.reload()

    expect(desktop.tab("destination:conversation")).to_be_visible()
    expect(desktop.tab("destination:agents")).to_be_visible()
    expect(desktop.tab("destination:settings")).to_be_visible()
    expect(desktop.view("destination:settings")).to_have_attribute(
        "data-tab-group-id", "right"
    )
    expect(desktop.active_view("left")).to_have_attribute(
        "data-view-id", "destination:agents"
    )
    expect(desktop.active_view("right")).to_have_attribute(
        "data-view-id", "destination:settings"
    )
    expect(desktop.root).to_have_attribute("style", resized)


def test_fullscreen_uses_the_viewport_and_persists_on_refresh(page: Page):
    """Any tab can occupy the viewport and exits through shared fullscreen chrome."""
    ChatView(page).goto()
    desktop = DesktopLayout(page)
    _open_destinations(page, "settings")
    desktop.maximize("destination:settings")

    view = desktop.view("destination:settings")
    expect(view).to_have_attribute("data-fullscreen", "true")
    viewport = page.viewport_size
    box = _rect(view)
    assert viewport
    assert box["x"] == 0 and box["y"] == 0
    assert abs(box["width"] - viewport["width"]) <= 1
    assert abs(box["height"] - viewport["height"]) <= 1
    expect(
        page.get_by_test_id("fullscreen-view-header-destination:settings")
    ).to_be_visible()

    page.reload()
    expect(view).to_have_attribute("data-fullscreen", "true")
    page.keyboard.press("Escape")
    expect(view).to_have_attribute("data-fullscreen", "false")
    expect(desktop.tab("destination:settings")).to_be_visible()


def test_tab_can_float_over_sidebar_resize_fullscreen_and_redock(page: Page):
    """Placement changes preserve the mounted View and its component state."""
    ChatView(page).goto()
    desktop = DesktopLayout(page)
    _open_destinations(page, "settings")

    # Settings owns local tab selection state. Choosing a non-default tab gives
    # us an observable remount detector: a replacement SettingsPage would
    # initialize back to Skills even if the generic View host looked stable.
    system_tab = page.get_by_test_id("settings-tab-system")
    system_tab.click()
    expect(system_tab).to_have_class(re.compile("tabActive"))

    def expect_settings_state_preserved() -> None:
        expect(system_tab).to_have_class(re.compile("tabActive"))

    desktop.float("destination:settings")

    view = desktop.view("destination:settings")
    expect(view).to_have_attribute("data-floating", "true")
    expect(view).to_have_attribute("data-tab-group-id", "floating")
    expect(desktop.tab("destination:settings")).to_have_count(0)
    expect_settings_state_preserved()

    desktop.drag_floating_view(
        "destination:settings",
        target_x=8,
        target_y=110,
    )
    moved = _rect(view)
    sidebar = _rect(page.get_by_test_id("sidebar"))
    assert moved["x"] < sidebar["x"] + sidebar["width"]
    expect_settings_state_preserved()

    desktop.resize_floating_view(
        "destination:settings",
        delta_x=80,
        delta_y=50,
    )
    page.wait_for_timeout(300)
    resized = _rect(view)
    assert resized["width"] >= moved["width"] + 50
    assert resized["height"] >= moved["height"] + 30
    expect_settings_state_preserved()

    desktop.maximize("destination:settings")
    expect(view).to_have_attribute("data-fullscreen", "true")
    expect_settings_state_preserved()
    page.keyboard.press("Escape")
    expect(view).to_have_attribute("data-floating", "true")
    expect_settings_state_preserved()

    page.get_by_test_id("dock-view-destination:settings-right").click()
    expect(view).to_have_attribute("data-tab-group-id", "right")
    expect(view).to_have_attribute("data-floating", "false")
    expect(desktop.tab("destination:settings")).to_be_visible()
    expect_settings_state_preserved()

    desktop.float("destination:settings")
    expect_settings_state_preserved()
    page.get_by_test_id("close-floating-view-destination:settings").click()
    expect(view).to_have_count(0)


def test_floating_bounds_focus_and_stacking_persist_on_refresh(page: Page):
    """Floating views remember geometry and the last-focused View."""
    ChatView(page).goto()
    desktop = DesktopLayout(page)
    _open_destinations(page, "settings")
    desktop.float("destination:settings")
    desktop.drag_floating_view(
        "destination:settings",
        target_x=1100,
        target_y=100,
    )
    _open_destinations(page, "agents")
    desktop.float("destination:agents")

    settings = desktop.view("destination:settings")
    agents = desktop.view("destination:agents")
    desktop.drag_floating_view(
        "destination:settings",
        target_x=180,
        target_y=140,
    )
    settings_box = _rect(settings)

    desktop.floating_header("destination:settings").click(position={"x": 40, "y": 20})
    settings_z = int(settings.evaluate("element => getComputedStyle(element).zIndex"))
    agents_z = int(agents.evaluate("element => getComputedStyle(element).zIndex"))
    assert settings_z > agents_z
    page.wait_for_timeout(300)

    page.reload()

    expect(settings).to_have_attribute("data-floating", "true")
    expect(agents).to_have_attribute("data-floating", "true")
    restored_box = _rect(settings)
    assert abs(restored_box["x"] - settings_box["x"]) <= 2
    assert abs(restored_box["y"] - settings_box["y"]) <= 2
    restored_settings_z = int(
        settings.evaluate("element => getComputedStyle(element).zIndex")
    )
    restored_agents_z = int(
        agents.evaluate("element => getComputedStyle(element).zIndex")
    )
    assert restored_settings_z > restored_agents_z
