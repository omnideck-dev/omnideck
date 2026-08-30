"""Tests for the process-only Browser host/session boundary."""

from unittest.mock import AsyncMock, MagicMock

from tests.unit.tools.browser.support.playwright_stubs import EventEmitterStub
from tools.browser.core.host import BrowserHost


class _Context(EventEmitterStub):
    def __init__(self) -> None:
        super().__init__()
        self.pages = []
        self.set_extra_http_headers = AsyncMock()
        self.add_init_script = AsyncMock()
        self.close = AsyncMock()


def _host(context: _Context) -> tuple[BrowserHost, MagicMock, MagicMock]:
    playwright = MagicMock()
    playwright.stop = AsyncMock()
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()
    host = BrowserHost(
        pw=playwright,
        browser=browser,
        locale="en-US",
        timezone_id="America/Chicago",
        accept_downloads=True,
        downloads_dir="/tmp/downloads",
        geolocation=None,
        permissions=[],
        proxy=None,
        headers={"Accept-Language": "en-US,en;q=0.9"},
        ua_string=None,
        ua_metadata=None,
    )
    return host, playwright, browser


async def test_host_creates_isolated_session_from_supplied_state() -> None:
    context = _Context()
    host, _playwright, browser = _host(context)
    state = {"cookies": [{"name": "session", "value": "one"}], "origins": []}

    session = await host.create_session(storage_state=state)

    assert session._context is context
    browser.new_context.assert_awaited_once_with(
        no_viewport=True,
        locale="en-US",
        timezone_id="America/Chicago",
        accept_downloads=True,
        geolocation=None,
        permissions=[],
        java_script_enabled=True,
        storage_state=state,
    )


async def test_host_and_session_have_independent_lifetimes() -> None:
    context = _Context()
    host, playwright, browser = _host(context)
    session = await host.create_session()

    await session.close_session()
    context.close.assert_awaited_once()
    browser.close.assert_not_awaited()

    await host.close()
    browser.close.assert_awaited_once()
    playwright.stop.assert_awaited_once()
