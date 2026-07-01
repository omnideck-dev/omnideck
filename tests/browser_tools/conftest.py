"""Fixtures for the browser-tools suite.

This suite drives the *real* browser tools (``browse_page``, ``click``,
``fill_field``) against hand-written HTML pages served over HTTP, using a
real headless Chrome. It exists to catch behavior the unit suite can't: the
unit tests stub Playwright, so the real DOM walker in ``page_view.py`` never
runs against a real document.

Two design constraints worth calling out:

* Pages are served over **HTTP, not ``file://``**. Chromium gives every
  ``file://`` document an opaque origin, which makes a ``file://`` iframe
  cross-origin to its ``file://`` parent — so ``iframe.contentDocument`` is
  null and the same-origin iframe scenarios become impossible to reproduce.
  Serving over ``http://127.0.0.1:<port>`` gives real same-origin iframes,
  and a second port gives a real cross-origin one.
* The tools resolve their browser through ``get_browser`` (imported per
  module). The ``browser_session`` fixture starts a real ``Browser`` and patches
  every ``get_browser`` binding to hand it back, so the actual tool functions
  run unchanged against it.

Kept out of the default unit ``testpaths``; run with ``just browser-tools``.
"""

from __future__ import annotations

import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import pytest
from aiohttp import web

from tools.browser.core.browser import Browser

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _free_port() -> int:
    """Grab an ephemeral localhost port for a fixture server to bind to."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _serve(port: int) -> web.AppRunner:
    """Start a static file server for the fixtures dir on *port*."""
    app = web.Application()
    app.router.add_static("/", str(FIXTURES_DIR))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    return runner


@dataclass(frozen=True)
class Servers:
    """Base URLs for the two fixture origins (same host, different ports)."""

    primary: str
    secondary: str

    def embed(
        self,
        iframe_src: str,
        *,
        on: str | None = None,
        width: str | None = None,
        height: str | None = None,
    ) -> str:
        """URL of a host page on origin *on* that embeds *iframe_src*.

        The generic embed-host fixture reads its iframe ``src`` (and optional
        ``width``/``height``) from the query string at runtime, so a test can
        point the iframe at any origin and size it — the fixture ports are
        ephemeral and can't be baked into a static page. Defaults to embedding
        on the primary origin at a viewport-filling (dominant) size; pass the
        secondary base as *iframe_src*'s origin for a cross-origin embed, or a
        small ``width``/``height`` for a non-dominant one.
        """
        host = on or self.primary
        params: dict[str, str] = {"src": iframe_src}
        if width is not None:
            params["width"] = width
        if height is not None:
            params["height"] = height
        return f"{host}/iframe/embed_host.html?{urlencode(params)}"


@pytest.fixture
async def servers() -> AsyncIterator[Servers]:
    """Serve the fixtures dir on two localhost ports (two origins)."""
    primary_port = _free_port()
    secondary_port = _free_port()

    primary_runner = await _serve(primary_port)
    secondary_runner = await _serve(secondary_port)
    try:
        yield Servers(
            primary=f"http://127.0.0.1:{primary_port}",
            secondary=f"http://127.0.0.1:{secondary_port}",
        )
    finally:
        await primary_runner.cleanup()
        await secondary_runner.cleanup()


class BrowserSession:
    """A real browser wired into the tools, with a helper to open tabs."""

    def __init__(self, browser: Browser) -> None:
        self.browser = browser

    async def open(self, url: str) -> str:
        """Open *url* in a new tab and return its stable tab id as a string."""
        page = await self.browser.new_page()
        await self.browser.navigate(url, page=page)
        tab_id = self.browser.tab_id_of(page)
        assert tab_id is not None
        return str(tab_id)


@pytest.fixture
async def browser_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[BrowserSession]:
    """A real headless Browser wired into every ``get_browser`` call site.

    Patching ``get_browser`` (rather than constructing an agent context) is
    the same seam the unit suite uses; here it's backed by a real browser so
    the tools exercise real Chromium. The post-tool screenshot is stubbed to a
    no-op so the tools don't need a live event/conversation context.
    """
    browser = await Browser.start(
        str(tmp_path / "profile"),
        headless=True,
        downloads_path=str(tmp_path / "downloads"),
    )
    browser._downloads_dir = str(tmp_path / "downloads")

    async def _get_live_browser() -> Browser:
        return browser

    for target in (
        "tools.browser.core.browser.get_browser",
        "tools.browser.core.get_browser",
        "tools.browser.snapshot_tool.get_browser",
        "tools.browser.interactions.get_browser",
        "tools.browser.read_content.get_browser",
        "tools.browser.events.get_browser",
    ):
        monkeypatch.setattr(target, _get_live_browser)

    async def _noop_emit(_page: object) -> None:
        return None

    monkeypatch.setattr("tools.browser.events._emit_screenshot", _noop_emit)

    try:
        yield BrowserSession(browser)
    finally:
        await browser.close()
