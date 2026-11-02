"""E2E coverage for the mobile-viewport layout adaptations.

Covers the two blockers reported when using Omnideck on a phone-sized
viewport: the composer being clipped below the visible viewport, and new
views landing in an unreachable second pane.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

from tests.e2e._protocol import bash, send_file, write_file
from tests.e2e.pages import ChatView, DesktopLayout, Sidebar

_MOBILE_VIEWPORT = {"width": 390, "height": 844}


def _rect(locator):
    box = locator.bounding_box()
    assert box
    return box


def test_composer_stays_within_the_visible_viewport(page: Page):
    """Regression test: the composer must never sit below 100vh on mobile."""
    page.set_viewport_size(_MOBILE_VIEWPORT)
    chat = ChatView(page).goto()

    composer_box = _rect(chat.composer)
    assert composer_box["y"] + composer_box["height"] <= _MOBILE_VIEWPORT["height"]


def test_sidebar_starts_collapsed_on_first_load(page: Page):
    """Mobile has no room to spare, so the sidebar defaults to collapsed."""
    page.set_viewport_size(_MOBILE_VIEWPORT)
    ChatView(page).goto()
    assert Sidebar(page).is_collapsed()


def test_new_views_open_in_the_single_visible_pane(page: Page):
    """A view that normally opens opposite the conversation (the right tab
    group) instead joins the conversation's pane, and the right tab group
    never renders."""
    page.set_viewport_size(_MOBILE_VIEWPORT)
    chat = ChatView(page).goto().new_conversation()
    desktop = DesktopLayout(page)

    hello = "/home/computron/hello.txt"
    chat.send(
        bash('echo "hello"')
        + write_file(hello, "hello")
        + send_file(hello)
    ).wait_streaming()

    assert chat.file_preview_btns.first.is_visible(), (
        "Agent did not produce a file output to preview"
    )
    chat.file_preview_btns.first.click()
    chat.preview.file_tabs.first.wait_for(state="visible", timeout=5_000)

    expect(desktop.tab_group("right")).to_have_count(0)
    expect(chat.preview.content).to_have_count(0)

    # The tab and its view host share a view.testid-derived key (distinct from
    # view.id, which `desktop.view()` looks up by) — use it directly.
    view_key = (
        chat.preview.file_tabs.first.get_attribute("data-testid") or ""
    ).removeprefix("view-tab-")
    view_host = page.get_by_test_id(f"desktop-view-{view_key}")
    expect(view_host).to_have_attribute("data-tab-group-id", "left")
