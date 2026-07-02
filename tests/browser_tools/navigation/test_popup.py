"""Clicking a target=_blank link opens and tracks a new tab."""

from __future__ import annotations

from tools.browser.interactions import click
from tools.browser.snapshot_tool import browse_page

from .._helpers import find_ref


async def test_target_blank_opens_new_tab(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/new-tab-link/opener.html")
    before = len(browser_session.browser.open_tabs())

    view = await browse_page(tab=tab)
    ref = find_ref(view, role="link", name="Open in new tab")
    assert ref is not None
    await click(ref, tab=tab)

    tabs = browser_session.browser.open_tabs()
    assert len(tabs) == before + 1

    # The new tab is tracked and addressable, showing the linked page.
    new_id = str(browser_session.browser.tab_id_of(tabs[-1]))
    assert "Opened in new tab" in await browse_page(tab=new_id)
