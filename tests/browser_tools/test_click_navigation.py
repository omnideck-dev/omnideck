"""click() must return a snapshot of the page it navigated to.

The failure is a timing race, not a cross-origin one: some sites start their
navigation a beat after the click returns (e.g. a JS click handler that runs
before setting location — measured ~500ms on nasa.gov, for same-origin links
too). If the post-click settle runs before the navigation has started, it
snapshots the old page. Reproduced here with a deferred same-origin navigation.
"""

from __future__ import annotations

from urllib.parse import urlencode

from tools.browser.interactions import click
from tools.browser.snapshot_tool import browse_page

from ._helpers import find_ref


async def _click_link(browser_session, servers, *, delay_ms: int) -> str:
    # Target is same-origin as the link page — origin is irrelevant to the bug.
    target = f"{servers.primary}/navigation/target.html"
    params = {"href": target, "delay": str(delay_ms)}
    url = f"{servers.primary}/navigation/link.html?{urlencode(params)}"
    tab = await browser_session.open(url)

    view = await browse_page(tab=tab)
    link_ref = find_ref(view, role="link", name="Go to target")
    assert link_ref is not None
    return await click(link_ref, tab=tab)


async def test_click_navigation_returns_new_page(browser_session, servers):
    # Navigation starts immediately on click.
    result = await _click_link(browser_session, servers, delay_ms=0)
    assert "Target page" in result
    assert "Link page" not in result


async def test_click_deferred_navigation_returns_new_page(browser_session, servers):
    # Navigation starts ~400ms after the click returns, as real sites do. The
    # post-click settle must not snapshot the old page before the new one loads.
    result = await _click_link(browser_session, servers, delay_ms=400)
    assert "Target page" in result
    assert "Link page" not in result
