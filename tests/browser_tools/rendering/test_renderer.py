"""Document-renderer behaviors that browse_page depends on.

These pin down the parts of document rendering most likely to break in a
refactor: shadow-DOM piercing, implicit interactivity, accessible-name
resolution, and viewport clipping vs full_page.
"""

from __future__ import annotations

import pytest

from tools.browser import browse_page, click

from .._helpers import find_ref


async def test_shadow_dom_is_pierced(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/shadow-dom/page.html")
    rendered = await browse_page(tab=tab)

    # Controls live inside a (closed) shadow root; the open-shadow init script
    # The renderer must surface them anyway.
    assert find_ref(rendered, role="button", name="Shadow button") is not None
    assert find_ref(rendered, role="textbox", name="Shadow field") is not None


async def test_stale_shadow_refs_are_removed_before_renumbering(open_tab, servers):
    """A newly assigned shadow ref must not collide with a stale hidden one."""
    tab = await open_tab(f"{servers.primary}/shadow-ref-cleanup/page.html")
    first_rendered = await browse_page(full_page=True, tab=tab)
    assert find_ref(first_rendered, role="button", name="First action") is not None
    switch_ref = find_ref(first_rendered, role="button", name="Switch actions")
    assert switch_ref is not None

    second_rendered = await click(switch_ref, tab=tab)
    assert find_ref(second_rendered, role="button", name="First action") is None
    current_ref = find_ref(second_rendered, role="button", name="Second action")
    assert current_ref is not None

    result = await click(current_ref, tab=tab)
    assert "Second action clicked" in result


async def test_implicit_interactivity(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/clickable-divs/page.html")
    rendered = await browse_page(tab=tab)

    # cursor:pointer and tabindex divs are promoted to clickable buttons...
    assert find_ref(rendered, role="button", name="Clickable div") is not None
    assert find_ref(rendered, role="button", name="Focusable div") is not None
    # ...a plain span is not.
    assert find_ref(rendered, role="button", name="Plain text") is None


async def test_accessible_name_resolution(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/accessible-names/page.html")
    rendered = await browse_page(tab=tab)

    assert find_ref(rendered, role="button", name="Aria labelled button") is not None
    assert find_ref(rendered, role="button", name="Labelledby text") is not None
    assert find_ref(rendered, role="textbox", name="For-attr label") is not None
    assert find_ref(rendered, role="textbox", name="Wrapping label") is not None
    assert find_ref(rendered, role="textbox", name="Placeholder name") is not None


@pytest.mark.xfail(
    strict=True,
    reason="aria-labelledby accepts multiple IDs, but the renderer resolves the raw value as one ID",
)
async def test_accessible_name_resolution_supports_multiple_labelledby_ids(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/accessible-names/page.html")
    rendered = await browse_page(tab=tab)

    assert find_ref(rendered, role="textbox", name="Billing address") is not None


@pytest.mark.xfail(
    strict=True,
    reason="promoted elements retain the renderer-injected aria-label after their text changes",
)
async def test_promoted_element_name_updates_after_click(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/label-toggle/page.html")
    rendered = await browse_page(tab=tab)
    ref = find_ref(rendered, role="button", name="Add to cart")
    assert ref is not None

    await click(ref, tab=tab)
    rerendered = await browse_page(tab=tab)

    assert find_ref(rerendered, role="button", name="Remove from cart") is not None


async def test_full_page_reveals_offscreen(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/tall-page/page.html")

    # 4000px down — clipped out of the default viewport rendering...
    default = await browse_page(tab=tab)
    assert find_ref(default, role="button", name="Bottom button") is None
    # ...but present with full_page=True.
    full = await browse_page(full_page=True, tab=tab)
    assert find_ref(full, role="button", name="Bottom button") is not None
