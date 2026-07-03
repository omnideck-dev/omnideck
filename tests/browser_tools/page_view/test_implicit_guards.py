"""Guards on implicit (cursor:pointer) interactivity.

A cursor:pointer wrapper that already contains a real control must not be
promoted to its own button (that would double-emit); an element whose only
content is an image is promoted and named from the image's alt.
"""

from __future__ import annotations

from tools.browser.snapshot_tool import browse_page

from .._helpers import find_ref


async def test_wrapper_with_interactive_child_not_double_emitted(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/nested-clickable/page.html")
    view = await browse_page(tab=tab)

    # The inner button is surfaced...
    assert find_ref(view, role="button", name="Inner real button") is not None
    # ...and exactly once — the cursor:pointer wrapper is not a second button.
    hits = sum(1 for line in view.splitlines() if "[button] Inner real button" in line)
    assert hits == 1


async def test_image_only_clickable_is_promoted(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/nested-clickable/page.html")
    view = await browse_page(tab=tab)
    # cursor:pointer with only an image -> button, named from the image's alt.
    assert find_ref(view, role="button", name="Image button") is not None
