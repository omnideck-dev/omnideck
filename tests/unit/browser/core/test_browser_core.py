from __future__ import annotations

import asyncio
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

import pytest
from playwright.async_api import Error as PlaywrightError

from browser.core.browser import Browser
from browser.core.downloads import DownloadInfo
from browser.core.exceptions import BrowserToolError
from browser.core.tab import Tab
from config import load_config
from tests.unit.tools.browser.support.playwright_stubs import EventEmitterStub

_MAX_OPEN_TABS = load_config().tools.browser.max_open_tabs


class FakePage(EventEmitterStub):
    def __init__(self, closed: bool = False) -> None:
        super().__init__()
        self._closed = closed
        self.url = ""

    def is_closed(self) -> bool:
        return self._closed

    async def close(self) -> None:
        self._closed = True
        self.emit("close", self)

    async def set_viewport_size(self, size: dict[str, int]) -> None:  # noqa: D401 - stub
        return None


class FakeContext(EventEmitterStub):
    def __init__(self, pages: list[FakePage] | None = None) -> None:
        super().__init__()
        self.pages = pages or []

    async def new_page(self) -> FakePage:
        # Real Playwright fires the context "page" event as the page is created.
        page = FakePage()
        self.pages.append(page)
        self.emit("page", page)
        return page


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tabs_filters_closed() -> None:
    """tabs returns only non-closed tabs in browser order."""
    pages = [FakePage(closed=False), FakePage(closed=True), FakePage(closed=False)]
    ctx = FakeContext(pages)
    browser = Browser(context=ctx, extra_headers={})  # type: ignore[arg-type]

    assert [tab._page_for_browser() for tab in browser.tabs()] == [pages[0], pages[2]]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tabs_empty() -> None:
    """tabs returns an empty list when no pages exist."""
    ctx = FakeContext([])
    browser = Browser(context=ctx, extra_headers={})  # type: ignore[arg-type]

    assert browser.tabs() == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_new_tab_assigns_monotonic_id() -> None:
    """Each new tab gets a fresh, monotonically-increasing ID."""
    ctx = FakeContext()
    browser = Browser(context=ctx, extra_headers={})  # type: ignore[arg-type]

    tab1 = await browser.new_tab()
    tab2 = await browser.new_tab()
    tab3 = await browser.new_tab()

    assert [tab1.id, tab2.id, tab3.id] == [1, 2, 3]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_new_tab_refuses_past_open_tab_limit() -> None:
    """new_tab raises once the open-tab limit is reached."""
    ctx = FakeContext()
    browser = Browser(context=ctx, extra_headers={})  # type: ignore[arg-type]

    for _ in range(_MAX_OPEN_TABS):
        await browser.new_tab()

    with pytest.raises(BrowserToolError, match="Tab limit reached"):
        await browser.new_tab()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_new_tab_allowed_after_closing_a_tab() -> None:
    """Closing a tab frees a slot so new_tab succeeds again."""
    ctx = FakeContext()
    browser = Browser(context=ctx, extra_headers={})  # type: ignore[arg-type]

    tabs = [await browser.new_tab() for _ in range(_MAX_OPEN_TABS)]

    # Closing one tab drops the open count below the limit.
    await tabs[0].close()

    # Should not raise now that a slot is free.
    await browser.new_tab()
    assert len(browser.tabs()) == _MAX_OPEN_TABS


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tab_id_not_reused_after_close() -> None:
    """Closing a tab does not free its ID for reuse."""
    ctx = FakeContext()
    browser = Browser(context=ctx, extra_headers={})  # type: ignore[arg-type]

    tab1 = await browser.new_tab()
    tab2 = await browser.new_tab()
    # Simulate Playwright's close event.
    await tab1.close()

    tab3 = await browser.new_tab()
    assert tab3.id == 3
    assert tab2.id == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_tab_by_id() -> None:
    """get_tab looks up tabs by their stable ID."""
    ctx = FakeContext()
    browser = Browser(context=ctx, extra_headers={})  # type: ignore[arg-type]

    tab1 = await browser.new_tab()
    tab2 = await browser.new_tab()

    assert browser.get_tab("1") is tab1
    assert browser.get_tab(2) is tab2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_tab_errors_when_id_unknown() -> None:
    ctx = FakeContext()
    browser = Browser(context=ctx, extra_headers={})  # type: ignore[arg-type]

    await browser.new_tab()

    with pytest.raises(ValueError, match="not found"):
        browser.get_tab("99")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_tab_id_missing_reports_not_found_even_when_no_tabs() -> None:
    """A specific tab id that doesn't exist should say 'not found', not
    'no open tabs' — the caller knew which tab they wanted, the right
    error is about that specific tab.
    """
    ctx = FakeContext()
    browser = Browser(context=ctx, extra_headers={})  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="not found"):
        browser.get_tab("3")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_concurrent_goto_on_same_tab_errors() -> None:
    """A second navigate while one is in flight on the same tab errors loudly."""
    ctx = FakeContext()
    browser = Browser(context=ctx, extra_headers={})  # type: ignore[arg-type]

    tab = await browser.new_tab()
    tab._begin_navigation()

    with pytest.raises(BrowserToolError, match="in flight"):
        await browser.navigate("https://example.com", tab=tab)


class AbortingPage(FakePage):
    """A page whose navigation aborts with net::ERR_ABORTED.

    ``on_goto`` stands in for what the browser does around the abort (start a
    download, commit a different navigation, or nothing).
    """

    def __init__(self, on_goto: Callable[[AbortingPage], None] | None = None) -> None:
        super().__init__()
        self.url = "https://previous.example.com/"
        self._on_goto = on_goto

    async def goto(self, url: str, wait_until: str = "load") -> None:
        if self._on_goto is not None:
            self._on_goto(self)
        raise PlaywrightError(f"Page.goto: net::ERR_ABORTED at {url}\nCall log:\n  - navigating")


class AbortingContext(FakeContext):
    def __init__(self, page: AbortingPage) -> None:
        super().__init__()
        self._page = page

    async def new_page(self) -> FakePage:
        self.pages.append(self._page)
        self.emit("page", self._page)
        return self._page


async def _browser_with_aborting_tab(page: AbortingPage) -> tuple[Browser, Tab, AsyncMock]:
    browser = Browser(context=AbortingContext(page), extra_headers={})  # type: ignore[arg-type]
    # Keep the no-download path fast; the real wait is several seconds.
    browser._ABORTED_NAV_DOWNLOAD_WAIT_S = 0.05
    tab = await browser.new_tab()
    finalize = AsyncMock(return_value="finalized")
    browser._finalize_action = finalize  # type: ignore[method-assign]
    return browser, tab, finalize


def _fake_download() -> MagicMock:
    """A Playwright download whose file never materialises."""
    download = MagicMock()
    download.path = AsyncMock(return_value=None)
    return download


def _fake_download_info() -> DownloadInfo:
    return DownloadInfo(path="/tmp/report.pdf", content_type="application/pdf", size_bytes=10, filename="report.pdf")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_aborted_goto_without_download_raises_instead_of_returning_old_page() -> None:
    """An aborted navigation that downloads nothing is an error, not the previous page."""
    browser, tab, finalize = await _browser_with_aborting_tab(AbortingPage())

    with pytest.raises(BrowserToolError, match=r"Navigation to https://target\.example\.com/ was aborted") as excinfo:
        await browser.navigate("https://target.example.com/", tab=tab)

    assert "net::ERR_ABORTED" in str(excinfo.value)
    assert "Call log" not in str(excinfo.value)
    finalize.assert_not_awaited()
    assert not tab._navigation_in_progress()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_aborted_goto_that_downloads_during_the_wait_finalizes() -> None:
    """The PDF-as-download case keeps returning the download result."""

    def download_shortly(p: AbortingPage) -> None:
        asyncio.get_running_loop().call_later(0.01, p.emit, "download", _fake_download())

    browser, tab, finalize = await _browser_with_aborting_tab(AbortingPage(on_goto=download_shortly))
    browser._ABORTED_NAV_DOWNLOAD_WAIT_S = 1.0

    assert await browser.navigate("https://target.example.com/report.pdf", tab=tab) == "finalized"
    finalize.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_aborted_goto_whose_download_fired_before_the_abort_finalizes() -> None:
    """A download event that arrives before goto raises is still recognised."""
    browser, tab, finalize = await _browser_with_aborting_tab(
        AbortingPage(on_goto=lambda p: p.emit("download", _fake_download()))
    )

    assert await browser.navigate("https://target.example.com/report.pdf", tab=tab) == "finalized"
    finalize.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_aborted_goto_ignores_downloads_recorded_by_other_tabs() -> None:
    """Another tab's download must not mask this tab's aborted navigation."""
    page = AbortingPage()
    browser, tab, finalize = await _browser_with_aborting_tab(page)
    # navigate clears the shared pending list up front, so record the other
    # tab's download once the goto is under way.
    page._on_goto = lambda _p: browser._pending_downloads.append(_fake_download_info())

    with pytest.raises(BrowserToolError, match="was aborted"):
        await browser.navigate("https://target.example.com/", tab=tab)
    finalize.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_aborted_goto_download_survives_another_tab_clearing_shared_state() -> None:
    """This tab's download still counts if another action clears the shared download list."""

    def download_then_cleared(p: AbortingPage) -> None:
        p.emit("download", _fake_download())
        # As if the download finished processing and another tab's action
        # then drained the shared state.
        browser._download_tasks.clear()
        browser._pending_downloads.clear()

    page = AbortingPage(on_goto=download_then_cleared)
    browser, tab, finalize = await _browser_with_aborting_tab(page)

    assert await browser.navigate("https://target.example.com/report.pdf", tab=tab) == "finalized"
    finalize.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_aborted_goto_superseded_by_another_navigation_finalizes_on_new_page() -> None:
    """If a different navigation committed (e.g. a client-side redirect), that page is the result."""

    def redirect(p: AbortingPage) -> None:
        p.url = "https://redirected.example.com/"

    browser, tab, finalize = await _browser_with_aborting_tab(AbortingPage(on_goto=redirect))

    assert await browser.navigate("https://target.example.com/", tab=tab) == "finalized"
    finalize.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_aborted_goto_removes_its_download_listener() -> None:
    """Each navigation's page-scoped download listener is removed afterwards."""
    page = AbortingPage()
    browser, tab, _ = await _browser_with_aborting_tab(page)
    listeners_before = len(page._listeners.get("download", []))

    with pytest.raises(BrowserToolError):
        await browser.navigate("https://target.example.com/", tab=tab)

    assert len(page._listeners.get("download", [])) == listeners_before
