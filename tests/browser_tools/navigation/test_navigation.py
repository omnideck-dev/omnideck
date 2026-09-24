"""Tab and history navigation: new_tab, close_tab, goto, go_back."""

from __future__ import annotations

import asyncio
import re

import pytest

from tools.browser import BrowserToolError, browse_page, close_tab, go_back, goto, new_tab


async def test_browse_page_rejects_blank_tab(_live_browser):
    view = await new_tab("about:blank")
    match = re.search(r"tab=(\d+)", view)
    assert match is not None

    with pytest.raises(BrowserToolError, match="Navigate to a page first"):
        await browse_page(tab=match.group(1))


async def test_new_tab_then_close(open_tab, servers):
    view = await new_tab(f"{servers.primary}/article/article.html")
    match = re.search(r"tab=(\d+)", view)
    assert match is not None
    tab = match.group(1)
    assert "Hubble Telescope" in view

    # The new tab is addressable by its id...
    assert "Hubble Telescope" in await browse_page(tab=tab)
    # ...and can be closed by id.
    assert f"Closed tab={tab}" in await close_tab(tab=tab)


async def test_goto_repoints_tab_and_go_back(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/article/article.html")

    view = await goto(f"{servers.primary}/downloads/links.html", tab=tab)
    assert "Downloads" in view

    back = await go_back(tab=tab)
    assert "Hubble Telescope" in back


async def test_parallel_goto_keeps_real_tabs_associated(open_tab, servers):
    """Concurrent navigation returns each real tab's own destination view."""
    first_tab = await open_tab(f"{servers.primary}/article/article.html")
    second_tab = await open_tab(f"{servers.primary}/downloads/links.html")

    first, second = await asyncio.gather(
        goto(f"{servers.primary}/scope/page.html", tab=first_tab),
        goto(f"{servers.primary}/signup-form/form.html", tab=second_tab),
    )

    assert "Alpha button" in first
    assert f"tab={first_tab}]" in first
    assert "Create your account" in second
    assert f"tab={second_tab}]" in second


async def test_concurrent_goto_on_same_tab_reports_in_flight(open_tab, servers):
    """Exactly one concurrent navigation on a tab is rejected as in flight."""
    tab = await open_tab(f"{servers.primary}/article/article.html")

    results = await asyncio.gather(
        goto(f"{servers.primary}/scope/page.html", tab=tab),
        goto(f"{servers.primary}/signup-form/form.html", tab=tab),
        return_exceptions=True,
    )

    errors = [result for result in results if isinstance(result, BaseException)]
    assert len(errors) == 1
    assert "in flight" in str(errors[0])
