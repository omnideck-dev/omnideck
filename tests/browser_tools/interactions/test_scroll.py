"""scroll_page moves the viewport and reveals off-screen content."""

from __future__ import annotations

import re

import pytest

from tools.browser import browse_page, click, execute_javascript, scroll_page

from .._helpers import find_ref


def _scroll_top(view: str) -> int:
    match = re.search(r"\[Viewport: (\d+)-", view)
    assert match is not None
    return int(match.group(1))


def _document_height(view: str) -> int:
    match = re.search(r" of (\d+)px", view)
    assert match is not None
    return int(match.group(1))


def _javascript_number(result: str) -> int:
    match = re.search(r"Result: (-?\d+)", result)
    assert match is not None
    return int(match.group(1))


async def test_scroll_reveals_offscreen_content(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/tall-page/page.html")
    view = await browse_page(tab=tab)
    # The bottom button is 4000px down — not in the initial viewport.
    assert find_ref(view, role="button", name="Bottom button") is None

    result = await scroll_page("bottom", tab=tab)
    assert find_ref(result, role="button", name="Bottom button") is not None


async def test_scroll_down_and_up_use_real_wheel_input(open_tab, servers):
    """Pixel scrolling exercises the Page.mouse wheel path in headed Chrome."""
    tab = await open_tab(f"{servers.primary}/tall-page/page.html")

    after_down = await scroll_page("down", amount=600, tab=tab)
    assert _scroll_top(after_down) > 0

    after_up = await scroll_page("up", amount=600, tab=tab)
    assert _scroll_top(after_up) < _scroll_top(after_down)


async def test_wheel_scroll_keeps_targeting_hovered_container(open_tab, servers):
    """A successful container scroll does not also move the document."""
    tab = await open_tab(f"{servers.primary}/scroll-container/page.html")
    initial = await browse_page(tab=tab)
    first_item = find_ref(initial, role="button", name="List item 1")
    assert first_item is not None

    await click(first_item, tab=tab)
    after_down = await scroll_page("down", amount=600, tab=tab)
    container_scroll = await execute_javascript(
        "document.getElementById('items').scrollTop",
        tab=tab,
    )

    assert _scroll_top(after_down) == _scroll_top(initial)
    assert _javascript_number(container_scroll) > 0


async def test_page_and_edge_scroll_directions_use_document_evaluation(open_tab, servers):
    """Page-sized and edge scrolling update the selected document viewport."""
    tab = await open_tab(f"{servers.primary}/tall-page/page.html")
    initial = await browse_page(tab=tab)

    after_page_down = await scroll_page("page_down", tab=tab)
    assert _scroll_top(after_page_down) > _scroll_top(initial)

    after_page_up = await scroll_page("page_up", tab=tab)
    assert _scroll_top(after_page_up) < _scroll_top(after_page_down)

    at_bottom = await scroll_page("bottom", tab=tab)
    assert _scroll_top(at_bottom) > _scroll_top(after_page_up)

    at_top = await scroll_page("top", tab=tab)
    assert _scroll_top(at_top) < _scroll_top(at_bottom)


async def test_page_scroll_targets_selected_iframe(open_tab, servers):
    """Page-sized scrolling evaluates inside the dominant iframe document."""
    url = servers.embed(f"{servers.primary}/tall-page/page.html")
    tab = await open_tab(url)

    initial = await browse_page(tab=tab)
    assert "Top of page" in initial

    after_page_down = await scroll_page("page_down", tab=tab)
    assert _scroll_top(after_page_down) > _scroll_top(initial)


async def test_wheel_scroll_targets_same_origin_selected_iframe(open_tab, servers):
    """Wheel input is aimed inside a same-origin selected document."""
    url = servers.embed(f"{servers.primary}/tall-page/page.html")
    tab = await open_tab(url)

    initial = await browse_page(tab=tab)
    assert "Top of page" in initial
    assert "Host page heading" not in initial

    after_down = await scroll_page("down", amount=600, tab=tab)
    assert _scroll_top(after_down) > _scroll_top(initial)

    after_up = await scroll_page("up", amount=600, tab=tab)
    assert _scroll_top(after_up) < _scroll_top(after_down)


async def test_wheel_scroll_targets_cross_origin_selected_iframe(open_tab, servers):
    """Wheel input is aimed through the browser into a cross-origin document."""
    url = servers.embed(f"{servers.secondary}/tall-page/page.html")
    tab = await open_tab(url)

    initial = await browse_page(tab=tab)
    assert "Top of page" in initial
    assert "Host page heading" not in initial

    after_down = await scroll_page("down", amount=600, tab=tab)
    assert _scroll_top(after_down) > _scroll_top(initial)

    after_up = await scroll_page("up", amount=600, tab=tab)
    assert _scroll_top(after_up) < _scroll_top(after_down)


async def test_viewport_height_includes_fixed_body_content(open_tab, servers):
    """Viewport metadata includes content hidden by a fixed-body scroll lock."""
    tab = await open_tab(f"{servers.primary}/scroll-lock/fixed-body.html")
    view = await browse_page(tab=tab)

    assert _document_height(view) > 2000


async def test_scroll_targets_active_modal_content(open_tab, servers):
    """Scrolling moves a long modal rather than its unavailable background."""
    tab = await open_tab(f"{servers.primary}/modal-dialog/scrollable.html")
    initial = await browse_page(tab=tab)
    assert find_ref(initial, role="button", name="Final modal action") is None

    after_down = await scroll_page("down", amount=1100, tab=tab)

    assert find_ref(after_down, role="button", name="Final modal action") is not None
    assert find_ref(after_down, role="button", name="Background action") is None


async def test_full_viewport_takeover_blocks_background_scroll(open_tab, servers):
    """Pointer blocking, rather than a scroll lock, owns the active surface."""
    tab = await open_tab(f"{servers.primary}/modal-dialog/aria-nonblocking.html?layout=takeover")
    initial = await browse_page(tab=tab)

    blocked = await scroll_page("down", amount=600, tab=tab)
    assert "blocked by an open modal dialog" in blocked
    assert _scroll_top(blocked) == _scroll_top(initial)

    accept_ref = find_ref(blocked, role="button", name="Accept and continue")
    assert accept_ref is not None
    after_accept = await click(accept_ref, tab=tab)
    after_down = await scroll_page("down", amount=600, tab=tab)

    assert "[Modal dialog open" not in after_accept
    assert _scroll_top(after_down) > _scroll_top(after_accept)


async def test_aria_banner_without_background_block_is_not_modal(open_tab, servers):
    """A banner leaves the visible background actionable and scrollable."""
    tab = await open_tab(f"{servers.primary}/modal-dialog/aria-nonblocking.html?layout=banner")
    initial = await browse_page(tab=tab)

    assert "[Modal dialog open" not in initial
    assert find_ref(initial, role="button", name="Accept and continue") is not None
    background_ref = find_ref(initial, role="button", name="Background action")
    assert background_ref is not None

    after_click = await click(background_ref, tab=tab)
    assert "Background activated" in after_click

    after_down = await scroll_page("down", amount=600, tab=tab)

    assert _scroll_top(after_down) > _scroll_top(initial)


async def test_body_lock_with_background_scroller_is_not_modal(open_tab, servers):
    """A body lock does not suppress an independently scrollable app shell."""
    tab = await open_tab(f"{servers.primary}/modal-dialog/aria-nonblocking.html?layout=app-shell")
    initial = await browse_page(tab=tab)

    assert "[Modal dialog open" not in initial
    assert find_ref(initial, role="button", name="Accept and continue") is not None
    assert find_ref(initial, role="button", name="Background action") is not None

    after_down = await scroll_page("down", amount=600, tab=tab)
    background_scroll = await execute_javascript(
        "document.querySelector('main').scrollTop",
        tab=tab,
    )

    assert "blocked by an open modal dialog" not in after_down
    assert _javascript_number(background_scroll) > 0


async def test_blocked_modal_scroll_explains_next_action_without_consuming_budget(open_tab, servers):
    """A short modal reports why the background cannot scroll."""
    tab = await open_tab(f"{servers.primary}/modal-dialog/native.html")

    result = await scroll_page("down", amount=600, tab=tab)

    assert "blocked by an open modal dialog" in result
    assert "Dismiss it before scrolling" in result
