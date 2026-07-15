"""DOM walker behaviors that browse_page depends on.

These pin down the parts of the page-view walker most likely to break in a
refactor: shadow-DOM piercing, implicit interactivity, accessible-name
resolution, and viewport clipping vs full_page.
"""

from __future__ import annotations

from tools.browser import browse_page, click

from .._helpers import find_ref


async def test_shadow_dom_is_pierced(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/shadow-dom/page.html")
    view = await browse_page(tab=tab)

    # Controls live inside a (closed) shadow root; the open-shadow init script
    # + walker must surface them anyway.
    assert find_ref(view, role="button", name="Shadow button") is not None
    assert find_ref(view, role="textbox", name="Shadow field") is not None


async def test_stale_shadow_refs_are_removed_before_renumbering(browser_session, servers):
    """A newly assigned shadow ref must not collide with a stale hidden one."""
    tab = await browser_session.open(f"{servers.primary}/shadow-ref-cleanup/page.html")
    first_view = await browse_page(full_page=True, tab=tab)
    assert find_ref(first_view, role="button", name="First action") is not None
    switch_ref = find_ref(first_view, role="button", name="Switch actions")
    assert switch_ref is not None

    second_view = await click(switch_ref, tab=tab)
    assert find_ref(second_view, role="button", name="First action") is None
    current_ref = find_ref(second_view, role="button", name="Second action")
    assert current_ref is not None

    result = await click(current_ref, tab=tab)
    assert "Second action clicked" in result


async def test_implicit_interactivity(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/clickable-divs/page.html")
    view = await browse_page(tab=tab)

    # cursor:pointer and tabindex divs are promoted to clickable buttons...
    assert find_ref(view, role="button", name="Clickable div") is not None
    assert find_ref(view, role="button", name="Focusable div") is not None
    # ...a plain span is not.
    assert find_ref(view, role="button", name="Plain text") is None


async def test_accessible_name_resolution(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/accessible-names/page.html")
    view = await browse_page(tab=tab)

    assert find_ref(view, role="button", name="Aria labelled button") is not None
    assert find_ref(view, role="button", name="Labelledby text") is not None
    assert find_ref(view, role="textbox", name="For-attr label") is not None
    assert find_ref(view, role="textbox", name="Wrapping label") is not None
    assert find_ref(view, role="textbox", name="Placeholder name") is not None


async def test_full_page_reveals_offscreen(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/tall-page/page.html")

    # 4000px down — clipped out of the default viewport view...
    default = await browse_page(tab=tab)
    assert find_ref(default, role="button", name="Bottom button") is None
    # ...but present with full_page=True.
    full = await browse_page(full_page=True, tab=tab)
    assert find_ref(full, role="button", name="Bottom button") is not None
