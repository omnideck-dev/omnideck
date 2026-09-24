"""Regression tests for interactions that open a new browser tab."""

from __future__ import annotations

from textwrap import dedent

from tools.browser import click
from tools.browser import browse_page

from .._helpers import find_ref, page_body

_OPENED = dedent("""\
    [h1] Opened in a new tab
    [1] [button] Confirm the report""")


async def _click_the_link(open_tab, servers) -> tuple[str, str]:
    tab = await open_tab(f"{servers.primary}/new-tab/page.html")
    view = await browse_page(tab=tab)
    result = await click(find_ref(view, role="link", name="Open the report"), tab=tab)
    return tab, result


async def test_click_returns_the_new_tab(open_tab, servers):
    _tab, result = await _click_the_link(open_tab, servers)

    # The snapshot is the newly opened page, not the one the link was clicked from.
    assert page_body(result) == _OPENED


async def test_new_tab_id_is_reported_and_addressable(open_tab, servers):
    tab, result = await _click_the_link(open_tab, servers)

    # The fixture opens exactly one tab and the click opens exactly one more.
    assert tab == "1"
    # The header names the tab the agent was moved to, and that id resolves: the
    # agent can keep working there.
    assert "tab=2]" in result
    assert page_body(await browse_page(tab="2")) == _OPENED


async def test_original_tab_stays_open(open_tab, servers):
    tab, _result = await _click_the_link(open_tab, servers)

    # Moving to the new tab must not cost the agent the one it came from.
    assert page_body(await browse_page(tab=tab)) == dedent("""\
        [h1] Original page
        [1] [link] Open the report""")


async def test_screenshot_follows_the_new_tab(open_tab, servers, monkeypatch):
    shots: list = []

    async def _record(page) -> None:
        shots.append(page)

    monkeypatch.setattr("tools.browser.events._emit_screenshot", _record)

    _tab, result = await _click_the_link(open_tab, servers)

    # The screenshot the UI renders has to be the tab the agent was handed. If it
    # still shot the tab the click started from, the agent would be reading tab 2
    # while the preview showed tab 1.
    assert shots
    assert shots[-1].url.endswith("/new-tab/opened.html")
    assert "tab=2]" in result
