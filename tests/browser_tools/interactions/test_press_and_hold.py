"""press_and_hold holds the mouse down on an element for a duration."""

from __future__ import annotations

from tools.browser import press_and_hold
from tools.browser import browse_page

from .._helpers import find_ref


async def test_press_and_hold_button(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/hold-button/page.html")
    view = await browse_page(tab=tab)

    ref = find_ref(view, role="button", name="Hold me")
    assert ref is not None

    # The fixture only reveals "Held long enough" after a >=500ms hold; the tool
    # also clamps duration to [500, 10000]ms, so 800ms comfortably qualifies.
    result = await press_and_hold(ref, duration_ms=800, tab=tab)
    assert "Held long enough" in result
