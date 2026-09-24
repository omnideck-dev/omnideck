import pytest

from browser.core.browser import Browser
from browser.core.exceptions import BrowserToolError
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
