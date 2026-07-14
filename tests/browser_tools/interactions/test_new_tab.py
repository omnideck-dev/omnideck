"""Clicking a link that opens a new tab lands the agent on that tab.

The browser layer worked out which tab the click settled on, but the result it
handed back carried no page, so every interaction tool rendered the tab it had
started from. Clicking a ``target="_blank"`` link came back as a byte-identical
snapshot of the original page: to the agent the click did nothing, while a real
tab sat open and unreachable behind it.
"""

from __future__ import annotations

import re
from textwrap import dedent

from tools.browser.interactions import click
from tools.browser.snapshot_tool import browse_page

from .._helpers import find_ref, page_body

_OPENED = dedent("""\
    [h1] Opened in a new tab
    [1] [button] Confirm the report""")


async def _click_the_link(browser_session, servers) -> tuple[str, str]:
    tab = await browser_session.open(f"{servers.primary}/new-tab/page.html")
    view = await browse_page(tab=tab)
    result = await click(find_ref(view, role="link", name="Open the report"), tab=tab)
    return tab, result


async def test_click_returns_the_new_tab(browser_session, servers):
    _tab, result = await _click_the_link(browser_session, servers)

    # The snapshot is the newly opened page, not the one the link was clicked from.
    assert page_body(result) == _OPENED


async def test_new_tab_id_is_reported_and_addressable(browser_session, servers):
    tab, result = await _click_the_link(browser_session, servers)

    # The header names the tab the agent has been moved to, so it can keep
    # working there. That id has to resolve to the new tab, not the old one.
    match = re.search(r"tab=(\d+)\]", result)
    assert match is not None
    new_tab = match.group(1)
    assert new_tab != tab
    assert page_body(await browse_page(tab=new_tab)) == _OPENED


async def test_original_tab_stays_open(browser_session, servers):
    tab, _result = await _click_the_link(browser_session, servers)

    # Moving to the new tab must not cost the agent the one it came from.
    assert page_body(await browse_page(tab=tab)) == dedent("""\
        [h1] Original page
        [1] [link] Open the report""")
