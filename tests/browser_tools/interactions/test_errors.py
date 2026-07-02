"""Error contracts: the messages/exceptions agents rely on when a call is wrong."""

from __future__ import annotations

import pytest

from tools.browser.core.exceptions import BrowserToolError
from tools.browser.interactions import click, fill_field
from tools.browser.select import select_option
from tools.browser.snapshot_tool import browse_page

from .._helpers import find_ref


async def test_unknown_ref_reports_not_found(browser_session, servers):
    # Refs are positional numbers, so "not found" is only guaranteed for a ref
    # that isn't stamped at all — a stale ref whose number still exists on the
    # current page would silently resolve to a different element.
    tab = await browser_session.open(f"{servers.primary}/signup-form/form.html")
    await browse_page(tab=tab)

    result = await click("999999", tab=tab)
    assert "not found" in result.lower()
    assert "browse_page" in result


async def test_fill_field_rejects_checkbox(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/signup-form/form.html")
    view = await browse_page(tab=tab)
    cb = find_ref(view, role="checkbox", name="I accept the terms of service")
    assert cb is not None

    with pytest.raises(BrowserToolError):
        await fill_field(cb, "x", tab=tab)


async def test_select_option_rejects_missing_value(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/signup-form/form.html")
    view = await browse_page(tab=tab)
    country = find_ref(view, role="combobox", name="Country")
    assert country is not None

    with pytest.raises(BrowserToolError) as exc:
        await select_option(country, "Atlantis", tab=tab)
    assert "not found" in str(exc.value).lower()
