"""Fixed and sticky controls remain available after scrolling (#419)."""

from __future__ import annotations

from tools.browser import browse_page, scroll_page

from .._helpers import find_ref


async def test_fixed_and_sticky_chrome_on_scroll(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/scroll-chrome/page.html")

    top = await browse_page(tab=tab)
    for name in ("Sticky button", "Fixed bar button", "Dialog button", "Overlay button"):
        assert find_ref(top, role="button", name=name) is not None, f"{name} missing at top"

    after = await scroll_page("bottom", tab=tab)
    # Visible persistent chrome remains usable after scrolling.
    assert find_ref(after, role="button", name="Sticky button") is not None
    assert find_ref(after, role="button", name="Fixed bar button") is not None
    # Fixed dialogs and large overlays remain visible too.
    assert find_ref(after, role="button", name="Dialog button") is not None
    assert find_ref(after, role="button", name="Overlay button") is not None

    full = await browse_page(full_page=True, tab=tab)
    for name in ("Sticky button", "Fixed bar button", "Dialog button", "Overlay button"):
        assert find_ref(full, role="button", name=name) is not None
