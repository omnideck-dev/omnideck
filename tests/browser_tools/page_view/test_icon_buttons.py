"""Icon buttons with no text name are named from their fallback labels.

An icon-only <button> carries no text content, so its accessible name comes
from aria-label, the title attribute, or a nested <svg><title>. All three must
surface the button (with a ref) rather than dropping it.
"""

from __future__ import annotations

from tools.browser.snapshot_tool import browse_page

from .._helpers import find_ref


async def test_aria_labelled_icon_button_is_exposed(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/icon-buttons/page.html")
    view = await browse_page(tab=tab)
    assert find_ref(view, role="button", name="Labelled icon") is not None


async def test_title_only_icon_button_is_exposed(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/icon-buttons/page.html")
    view = await browse_page(tab=tab)
    assert find_ref(view, role="button", name="Titled icon") is not None


async def test_svg_title_icon_button_is_exposed(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/icon-buttons/page.html")
    view = await browse_page(tab=tab)
    assert find_ref(view, role="button", name="SVG titled icon") is not None
