"""scroll_page moves the viewport and reveals off-screen content."""

from __future__ import annotations

from tools.browser.interactions import scroll_page
from tools.browser.snapshot_tool import browse_page

from .._helpers import find_ref


async def test_scroll_reveals_offscreen_content(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/tall-page/page.html")
    view = await browse_page(tab=tab)
    # The bottom button is 4000px down — not in the initial viewport.
    assert find_ref(view, role="button", name="Bottom button") is None

    result = await scroll_page("bottom", tab=tab)
    assert find_ref(result, role="button", name="Bottom button") is not None
