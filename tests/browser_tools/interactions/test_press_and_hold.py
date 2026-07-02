"""press_and_hold holds the mouse down on an element for a duration."""

from __future__ import annotations

from tools.browser.interactions import press_and_hold
from tools.browser.snapshot_tool import browse_page

from .._helpers import find_ref


async def test_press_and_hold_button(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/hold-button/page.html")
    view = await browse_page(tab=tab)

    ref = find_ref(view, role="button", name="Hold me")
    assert ref is not None

    result = await press_and_hold(ref, duration_ms=800, tab=tab)
    assert "Held long enough" in result
