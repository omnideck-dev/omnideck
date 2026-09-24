"""Rendering settles the document it actually represents."""

from __future__ import annotations

import time
from urllib.parse import quote

from tools.browser import browse_page, click, fill_field

from .._helpers import find_ref


async def test_browse_captures_live_page_without_settling(open_tab, servers):
    """An explicit browse returns the current state of a continuously changing page."""
    tab = await open_tab(f"{servers.primary}/settle/continuous.html")

    started = time.monotonic()
    rendered = await browse_page(tab=tab)
    elapsed = time.monotonic() - started

    assert "Live status" in rendered
    assert "Update" in rendered
    assert elapsed < 1.0


async def test_interaction_settles_dominant_iframe(open_tab, servers):
    """An interaction waits for mutations in the active iframe, not its host."""
    iframe = f"{servers.primary}/settle/iframe.html"
    tab = await open_tab(servers.embed(iframe))

    rendered = await browse_page(tab=tab)
    query_ref = find_ref(rendered, role="textbox", name="Query")
    assert query_ref is not None

    result = await fill_field(query_ref, "browser", tab=tab)

    assert "Update complete" in result
    assert "Updating" not in result


async def test_rendering_retries_when_document_is_replaced(open_tab, servers):
    """A redirect during settling is observed from its replacement document."""
    final = f"{servers.primary}/settle/redirect-final.html"
    middle = f"{servers.primary}/settle/redirect-middle.html?target={quote(final, safe='')}"
    start = f"{servers.primary}/settle/redirect-start.html?target={quote(middle, safe='')}"
    tab = await open_tab(start)

    rendered = await browse_page(tab=tab)
    continue_ref = find_ref(rendered, role="link", name="Continue")
    assert continue_ref is not None

    result = await click(continue_ref, tab=tab)

    assert "Redirect complete" in result
    assert final in result
