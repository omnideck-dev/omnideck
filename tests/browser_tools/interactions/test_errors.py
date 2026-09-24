"""Error contracts: the messages/exceptions agents rely on when a call is wrong."""

from __future__ import annotations

import pytest

from tools.browser import BrowserToolError, browse_page, click, fill_field, select_option

from .._helpers import find_ref


async def test_unknown_ref_reports_not_found(open_tab, servers):
    # Refs are positional numbers, so "not found" is only guaranteed for a ref
    # that isn't stamped at all — a stale ref whose number still exists on the
    # current page would silently resolve to a different element.
    tab = await open_tab(f"{servers.primary}/signup-form/form.html")
    await browse_page(tab=tab)

    result = await click("999999", tab=tab)
    assert "not found" in result.lower()
    assert "browse_page" in result


async def test_ambiguous_ref_reports_all_matching_elements(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/clone-ref/page.html")
    rendered = await browse_page(tab=tab)
    ref = find_ref(rendered, role="button", name="Duplicate me")
    assert ref is not None

    await click(ref, tab=tab)
    result = await click(ref, tab=tab)

    assert "matched 2 elements" in result
    assert "browse_page()" in result


async def test_fill_field_rejects_checkbox(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/signup-form/form.html")
    view = await browse_page(tab=tab)
    cb = find_ref(view, role="checkbox", name="I accept the terms of service")
    assert cb is not None

    with pytest.raises(BrowserToolError):
        await fill_field(cb, "x", tab=tab)


async def test_select_option_rejects_missing_value(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/signup-form/form.html")
    view = await browse_page(tab=tab)
    country = find_ref(view, role="combobox", name="Country")
    assert country is not None

    with pytest.raises(BrowserToolError) as exc:
        await select_option(country, "Atlantis", tab=tab)
    assert "not found" in str(exc.value).lower()
