"""Iframe selection in rendered browser documents.

A dominant iframe — one covering more than ~25% of the viewport, same OR cross
origin — is detected and the tools switch to operating *inside* it, so its
controls become the rendered document and the host page drops out. Playwright drives
frames of either origin, so both are covered.

Small / non-dominant and multiple iframes are not surfaced yet; that's a
separate refactor (plans/iframe_per_frame_page_view.md).
"""

from __future__ import annotations

import asyncio

import pytest
from aiohttp import web

from browser.core.document import Document
from tools.browser import browse_page, click, fill_field, new_tab

from .._helpers import find_ref


async def test_dominant_same_origin_iframe_becomes_selected_document(open_tab, servers):
    # The widget fills the viewport, so the tools operate inside it: its
    # controls are rendered and the host page is not.
    url = servers.embed(f"{servers.primary}/iframe-widget/widget.html")
    tab = await open_tab(url)
    rendered = await browse_page(tab=tab)

    assert find_ref(rendered, role="textbox", name="Email address") is not None
    assert find_ref(rendered, role="button", name="Continue") is not None
    assert "Host page heading" not in rendered


async def test_dominant_cross_origin_iframe_becomes_selected_document(open_tab, servers):
    # Same as above but the widget is served from the secondary origin.
    # Playwright drives frames of any origin, so a dominant cross-origin iframe
    # is entered just like a same-origin one.
    url = servers.embed(f"{servers.secondary}/iframe-widget/widget.html")
    tab = await open_tab(url)
    rendered = await browse_page(tab=tab)

    assert find_ref(rendered, role="textbox", name="Email address") is not None
    assert find_ref(rendered, role="button", name="Continue") is not None
    assert "Host page heading" not in rendered


@pytest.mark.parametrize("dominant", [True, False])
async def test_iframe_loading_during_settle_reconsiders_host_selection(
    _live_browser, servers, monkeypatch, dominant,
):
    """Real iframe loading must not leave the early host selection cached."""
    release_response = asyncio.Event()

    async def widget(_request):
        await release_response.wait()
        return web.Response(
            text='<html><body><label>Email address<input></label>'
            '<button>Continue</button></body></html>',
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/widget", widget)
    runner = web.AppRunner(app)
    await runner.setup()

    original_settle = Document.settle

    async def settle_after_response_is_released(document, waits):
        # Hold the cross-origin response until selection has already chosen
        # the host. Keep the real load/DOM waits and renderer: no timing sleeps
        # or fake selection results, even on fast local machines.
        release_response.set()
        return await original_settle(document, waits)

    monkeypatch.setattr(Document, "settle", settle_after_response_is_released)
    try:
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        port = runner.addresses[0][1]
        rendered = await new_tab(servers.embed(
            f"http://127.0.0.1:{port}/widget",
            width="92vw" if dominant else "100px",
            height="92vh" if dominant else "100px",
        ))
        if dominant:
            assert find_ref(rendered, role="textbox", name="Email address") is not None
            assert find_ref(rendered, role="button", name="Continue") is not None
            assert "Host page heading" not in rendered
        else:
            assert "Host page heading" in rendered
            assert find_ref(rendered, role="textbox", name="Email address") is None
    finally:
        release_response.set()
        await runner.cleanup()


async def test_cross_origin_iframe_supports_physical_input(open_tab, servers):
    """Frame-scoped locators drive the owning tab's keyboard and mouse."""
    url = servers.embed(f"{servers.secondary}/iframe-widget/widget.html")
    tab = await open_tab(url)
    rendered = await browse_page(tab=tab)

    email = find_ref(rendered, role="textbox", name="Email address")
    assert email is not None
    filled = await fill_field(email, "frame@example.com", tab=tab)
    assert "Email address = frame@example.com" in filled

    terms = find_ref(filled, role="checkbox", name="Accept terms")
    assert terms is not None
    checked = await click(terms, tab=tab)
    assert "Accept terms (checked)" in checked


async def test_in_page_click_reveals_dominant_iframe(open_tab, servers):
    # On load there is no iframe, so the host document is selected. Clicking injects
    # a viewport-filling iframe WITHOUT navigating; the in-page branch must
    # repoint the tools into the newly dominant frame.
    tab = await open_tab(f"{servers.primary}/iframe-widget/reveal-host.html")
    rendered = await browse_page(tab=tab)
    assert "Host page heading" in rendered

    opener = find_ref(rendered, role="button", name="Open widget")
    assert opener is not None
    after = await click(opener, tab=tab)

    assert find_ref(after, role="textbox", name="Email address") is not None
    assert find_ref(after, role="button", name="Continue") is not None
    assert "Host page heading" not in after


async def test_in_page_click_closing_dominant_iframe_returns_to_host(open_tab, servers):
    # Reveal the dominant iframe, then close it from inside. Removing the iframe
    # leaves no dominant frame, so the in-page branch must select the host
    # the host page.
    tab = await open_tab(f"{servers.primary}/iframe-widget/reveal-host.html")
    rendered = await browse_page(tab=tab)
    opener = find_ref(rendered, role="button", name="Open widget")
    assert opener is not None
    inside = await click(opener, tab=tab)

    closer = find_ref(inside, role="button", name="Close widget")
    assert closer is not None
    after = await click(closer, tab=tab)

    assert "Host page heading" in after
    assert find_ref(after, role="button", name="Open widget") is not None
    assert find_ref(after, role="textbox", name="Email address") is None
