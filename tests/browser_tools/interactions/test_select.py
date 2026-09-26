"""Dropdown selection, change events, and navigation outcomes."""

from __future__ import annotations

import pytest

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


async def test_long_select_dispatches_change(open_tab, servers):
    """Long dropdown lists select the requested option and notify the page."""
    tab = await open_tab(f"{servers.primary}/long-select/page.html")
    view = await browse_page(tab=tab)
    item = find_ref(view, role="combobox", name="Item")
    assert item is not None

    result = await select_option(item, "Item 35", tab=tab)

    assert "Item = Item 35" in result
    assert "Selected Item 35" in result


@pytest.mark.parametrize("reload", [False, True], ids=["navigation", "same-url-reload"])
@pytest.mark.parametrize("embedded", [False, True], ids=["main-frame", "cross-origin-frame"])
async def test_select_option_succeeds_when_change_navigates(open_tab, servers, reload, embedded):
    url = f"{servers.secondary}/select-navigation/page.html?reload={str(reload).lower()}"
    if embedded:
        url = servers.embed(url)
    tab = await open_tab(url)
    view = await browse_page(tab=tab)
    location = find_ref(view, role="combobox", name="Location")
    assert location is not None

    result = await select_option(location, "Remote (US)", tab=tab)

    assert "Location = Remote (US)" in result
    assert "Showing remote jobs" in result
    assert "Selection events: input=1, change=1" in result
