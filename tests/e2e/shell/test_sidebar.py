"""E2E tests for the collapsible navigation sidebar."""

from playwright.sync_api import Page, expect

from tests.e2e.pages import ChatView, Sidebar


def _sidebar_order(page: Page, selector: str) -> list[str]:
    """Return the DOM order for one reorderable sidebar group."""
    return page.locator(selector).evaluate_all("""rows => rows.map((row) => row.getAttribute('data-reorder-id'))""")


def _drag_below(page: Page, source_testid: str, target_testid: str) -> None:
    """Drag one sidebar row below another row."""
    source = page.get_by_test_id(source_testid)
    target = page.get_by_test_id(target_testid)
    source_box = source.bounding_box()
    target_box = target.bounding_box()
    assert source_box is not None
    assert target_box is not None

    page.mouse.move(
        source_box["x"] + source_box["width"] / 2,
        source_box["y"] + source_box["height"] / 2,
    )
    page.mouse.down()
    page.mouse.move(
        target_box["x"] + target_box["width"] / 2,
        target_box["y"] + target_box["height"] * 0.8,
        steps=8,
    )
    page.mouse.up()


def test_sidebar_collapses_and_expands(page: Page):
    """Toggling the sidebar flips its collapsed state."""
    ChatView(page).goto()
    sidebar = Sidebar(page)

    sidebar.set_collapsed(False)
    assert not sidebar.is_collapsed()

    sidebar.toggle.click()
    page.wait_for_timeout(250)
    assert sidebar.is_collapsed()

    sidebar.toggle.click()
    page.wait_for_timeout(250)
    assert not sidebar.is_collapsed()


def test_collapsed_state_persists_across_reload(page: Page):
    """The collapsed choice survives a page reload (localStorage-backed)."""
    ChatView(page).goto()
    sidebar = Sidebar(page)

    sidebar.set_collapsed(True)
    assert sidebar.is_collapsed()

    page.reload()
    expect(sidebar.root).to_have_attribute("data-collapsed", "true")

    sidebar.set_collapsed(False)
    page.reload()
    expect(sidebar.root).to_have_attribute("data-collapsed", "false")


def test_new_chat_button_is_reachable(page: Page):
    """The New chat button works in both collapsed and expanded states."""
    ChatView(page).goto()
    sidebar = Sidebar(page)

    sidebar.set_collapsed(False)
    expect(sidebar.new_chat).to_be_visible()

    sidebar.set_collapsed(True)
    expect(sidebar.new_chat).to_be_visible()


def test_destination_order_supports_drag_keyboard_context_menu_and_persistence(
    page: Page,
):
    """Destination rows reorder without losing click or collapsed-rail behavior."""
    ChatView(page).goto()
    sidebar = Sidebar(page)
    sidebar.set_collapsed(False)
    page.evaluate("localStorage.removeItem('omnideck_sidebar_navigation_order')")
    page.reload()

    selector = "[data-testid^='sidebar-nav-']"
    assert _sidebar_order(page, selector)[:4] == [
        "browser",
        "agents",
        "routines",
        "artifacts",
    ]

    # Movement below the four-pixel drag threshold remains a normal click.
    routines = page.get_by_test_id("sidebar-nav-routines")
    routines_box = routines.bounding_box()
    assert routines_box is not None
    page.mouse.move(
        routines_box["x"] + routines_box["width"] / 2,
        routines_box["y"] + routines_box["height"] / 2,
    )
    page.mouse.down()
    page.mouse.move(
        routines_box["x"] + routines_box["width"] / 2 + 2,
        routines_box["y"] + routines_box["height"] / 2 + 2,
    )
    page.mouse.up()
    expect(page.get_by_test_id("routines-view")).to_be_visible()

    _drag_below(page, "sidebar-nav-agents", "sidebar-nav-artifacts")
    assert _sidebar_order(page, selector)[:4] == [
        "browser",
        "routines",
        "artifacts",
        "agents",
    ]
    expect(page.get_by_test_id("routines-view")).to_be_visible()

    page.reload()
    assert _sidebar_order(page, selector)[:4] == [
        "browser",
        "routines",
        "artifacts",
        "agents",
    ]

    page.get_by_test_id("sidebar-nav-agents").click(button="right")
    page.get_by_test_id("sidebar-reorder-move-up").click()
    assert _sidebar_order(page, selector)[:4] == [
        "browser",
        "routines",
        "agents",
        "artifacts",
    ]

    agents = page.get_by_test_id("sidebar-nav-agents")
    agents.focus()
    agents.press("Alt+ArrowUp")
    assert _sidebar_order(page, selector)[:4] == [
        "browser",
        "agents",
        "routines",
        "artifacts",
    ]

    sidebar.set_collapsed(True)
    _drag_below(page, "sidebar-nav-agents", "sidebar-nav-routines")
    assert _sidebar_order(page, selector)[:4] == [
        "browser",
        "routines",
        "agents",
        "artifacts",
    ]
