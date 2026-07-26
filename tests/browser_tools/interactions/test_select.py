"""Native selection and the long-list JavaScript fallback."""

from __future__ import annotations

from tools.browser import browse_page, select_option

from .._helpers import find_ref


async def test_select_result_uses_current_selection(open_tab, servers):
    """Rendered value follows current selection, not initial selected markup."""
    tab = await open_tab(f"{servers.primary}/selected-option/page.html")
    view = await browse_page(tab=tab)
    fruit = find_ref(view, role="combobox", name="Fruit")
    assert fruit is not None

    result = await select_option(fruit, "Banana", tab=tab)

    assert "Fruit = Banana" in result
    assert "Selected Banana" in result


async def test_long_select_dispatches_change_after_javascript_fallback(open_tab, servers):
    """Targets beyond 30 options skip keyboard traversal but still notify the page."""
    tab = await open_tab(f"{servers.primary}/long-select/page.html")
    view = await browse_page(tab=tab)
    item = find_ref(view, role="combobox", name="Item")
    assert item is not None

    result = await select_option(item, "Item 35", tab=tab)

    assert "Item = Item 35" in result
    assert "Selected Item 35" in result
