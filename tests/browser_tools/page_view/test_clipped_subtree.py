"""Interactive content inside a zero-size (boxless) container is still surfaced.

A dropdown/popover anchored to a width:0;height:0 element — the Floating UI /
Popper "reference" pattern — has a container whose own box is off-screen, but
its children render at a visible spot. In viewport mode the walker would prune
an off-screen container's whole subtree; the 'clipped' verdict makes it recurse
*through* the boxless anchor instead, so the menu items aren't dropped.
"""

from __future__ import annotations

from tools.browser.snapshot_tool import browse_page

from .._helpers import find_ref


async def test_dropdown_in_zero_size_anchor_is_surfaced(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/dropdown-menu/page.html")
    # Default (viewport) mode, so vpPos/clipped actually runs — not full_page.
    view = await browse_page(tab=tab)

    assert find_ref(view, role="button", name="Open menu") is not None
    # These live inside the zero-size anchor; only the 'clipped' recursion reaches them.
    assert find_ref(view, role="button", name="Profile") is not None
    assert find_ref(view, role="button", name="Settings") is not None
    assert find_ref(view, role="button", name="Log out") is not None
