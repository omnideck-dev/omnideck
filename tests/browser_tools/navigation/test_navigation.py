"""Tab and history navigation: new_tab, close_tab, goto, go_back."""

from __future__ import annotations

import re

from tools.browser.interactions import go_back
from tools.browser.navigation import close_tab, goto, new_tab
from tools.browser.snapshot_tool import browse_page


async def test_new_tab_then_close(browser_session, servers):
    view = await new_tab(f"{servers.primary}/article/article.html")
    match = re.search(r"tab=(\d+)", view)
    assert match is not None
    tab = match.group(1)
    assert "Hubble Telescope" in view

    # The new tab is addressable by its id...
    assert "Hubble Telescope" in await browse_page(tab=tab)
    # ...and can be closed by id.
    assert f"Closed tab={tab}" in await close_tab(tab=tab)


async def test_goto_repoints_tab_and_go_back(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/article/article.html")

    view = await goto(f"{servers.primary}/downloads/links.html", tab=tab)
    assert "Downloads" in view

    back = await go_back(tab=tab)
    assert "Hubble Telescope" in back
