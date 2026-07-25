"""Sticky/fixed chrome on scroll.

Once scrolled, the walker drops persistent chrome (sticky nav, small fixed
bars) so it isn't re-emitted on every snapshot — but keeps a fixed dialog and
a large fixed overlay (the modal case), which the agent still needs to act on.
"""

from __future__ import annotations

from tools.browser import scroll_page
from tools.browser import browse_page

from .._helpers import find_ref


async def test_fixed_and_sticky_chrome_on_scroll(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/scroll-chrome/page.html")

    top = await browse_page(tab=tab)
    for name in ("Sticky button", "Fixed bar button", "Dialog button", "Overlay button"):
        assert find_ref(top, role="button", name=name) is not None, f"{name} missing at top"

    after = await scroll_page("bottom", tab=tab)
    # Persistent chrome is dropped once scrolled...
    assert find_ref(after, role="button", name="Sticky button") is None
    assert find_ref(after, role="button", name="Fixed bar button") is None
    # ...but a fixed dialog and a large fixed overlay survive (modal scroll).
    assert find_ref(after, role="button", name="Dialog button") is not None
    assert find_ref(after, role="button", name="Overlay button") is not None
