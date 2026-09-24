"""Clicking a target=_blank link opens and tracks a new tab."""

from __future__ import annotations

from tools.browser import click
from tools.browser import browse_page

from .._helpers import find_ref


async def test_target_blank_opens_new_tab(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/new-tab-link/opener.html")

    view = await browse_page(tab=tab)
    ref = find_ref(view, role="link", name="Open in new tab")
    assert ref is not None
    # target=_blank opens a separate, monotonically numbered tab.
    await click(ref, tab=tab)

    # The new tab is tracked and addressable through the public tool surface.
    assert "Opened in new tab" in await browse_page(tab="2")
