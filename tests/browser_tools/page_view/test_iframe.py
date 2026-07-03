"""Iframe content in the page view.

A dominant iframe — one covering more than ~25% of the viewport, same OR cross
origin — is detected and the tools switch to operating *inside* it, so its
controls become the page view and the host page drops out. Playwright drives
frames of either origin, so both are covered.

Small / non-dominant and multiple iframes are not surfaced yet; that's a
separate refactor (plans/iframe_per_frame_page_view.md).
"""

from __future__ import annotations

from tools.browser.snapshot_tool import browse_page

from .._helpers import find_ref


async def test_dominant_same_origin_iframe_becomes_the_page_view(browser_session, servers):
    # The widget fills the viewport, so the tools operate inside it: its
    # controls are the page view and the host page is not.
    url = servers.embed(f"{servers.primary}/iframe-widget/widget.html")
    tab = await browser_session.open(url)
    view = await browse_page(tab=tab)

    assert find_ref(view, role="textbox", name="Email address") is not None
    assert find_ref(view, role="button", name="Continue") is not None
    assert "Host page heading" not in view


async def test_dominant_cross_origin_iframe_becomes_the_page_view(browser_session, servers):
    # Same as above but the widget is served from the secondary origin.
    # Playwright drives frames of any origin, so a dominant cross-origin iframe
    # is entered just like a same-origin one.
    url = servers.embed(f"{servers.secondary}/iframe-widget/widget.html")
    tab = await browser_session.open(url)
    view = await browse_page(tab=tab)

    assert find_ref(view, role="textbox", name="Email address") is not None
    assert find_ref(view, role="button", name="Continue") is not None
    assert "Host page heading" not in view
