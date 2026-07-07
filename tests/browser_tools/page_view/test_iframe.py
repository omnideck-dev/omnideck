"""Iframe content in the page view.

A dominant iframe — one covering more than ~25% of the viewport, same OR cross
origin — is detected and the tools switch to operating *inside* it, so its
controls become the page view and the host page drops out. Playwright drives
frames of either origin, so both are covered.

Small / non-dominant and multiple iframes are not surfaced yet; that's a
separate refactor (plans/iframe_per_frame_page_view.md).
"""

from __future__ import annotations

from tools.browser.interactions import click
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


async def test_in_page_click_reveals_dominant_iframe(browser_session, servers):
    # On load there is no iframe, so the view is the host page. Clicking injects
    # a viewport-filling iframe WITHOUT navigating; the in-page branch must
    # repoint the tools into the newly dominant frame.
    tab = await browser_session.open(f"{servers.primary}/iframe-widget/reveal-host.html")
    view = await browse_page(tab=tab)
    assert "Host page heading" in view

    opener = find_ref(view, role="button", name="Open widget")
    assert opener is not None
    after = await click(opener, tab=tab)

    assert find_ref(after, role="textbox", name="Email address") is not None
    assert find_ref(after, role="button", name="Continue") is not None
    assert "Host page heading" not in after


async def test_in_page_click_closing_dominant_iframe_returns_to_host(browser_session, servers):
    # Reveal the dominant iframe, then close it from inside. Removing the iframe
    # leaves no dominant frame, so the in-page branch must drop the view back to
    # the host page.
    tab = await browser_session.open(f"{servers.primary}/iframe-widget/reveal-host.html")
    view = await browse_page(tab=tab)
    opener = find_ref(view, role="button", name="Open widget")
    assert opener is not None
    inside = await click(opener, tab=tab)

    closer = find_ref(inside, role="button", name="Close widget")
    assert closer is not None
    after = await click(closer, tab=tab)

    assert "Host page heading" in after
    assert find_ref(after, role="button", name="Open widget") is not None
    assert find_ref(after, role="textbox", name="Email address") is None
