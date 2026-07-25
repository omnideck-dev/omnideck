"""Native selection and the long-list JavaScript fallback."""

from __future__ import annotations

from tools.browser import browse_page, select_option

from .._helpers import find_ref


async def test_long_select_dispatches_change_after_javascript_fallback(open_tab, servers):
    """Targets beyond 30 options skip keyboard traversal but still notify the page."""
    tab = await open_tab(f"{servers.primary}/long-select/page.html")
    view = await browse_page(tab=tab)
    item = find_ref(view, role="combobox", name="Item")
    assert item is not None

    result = await select_option(item, "Item 35", tab=tab)

    assert "Item = Item 35" in result
    assert "Selected Item 35" in result
