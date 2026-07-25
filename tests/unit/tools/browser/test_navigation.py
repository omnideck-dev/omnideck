"""Unit tests for goto / new_tab / close_tab."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tools.browser import BrowserToolError, close_tab, goto, new_tab
from tools.browser.core.browser import ActionResult
from tools.browser.core.rendering import RenderedDocument


class _StubPage:
    def __init__(self, url: str = "about:blank") -> None:
        self.url = url
        self._closed = False

    def is_closed(self) -> bool:
        return self._closed

    async def close(self) -> None:
        self._closed = True


class _StubTab:
    def __init__(self, tab_id: int, page: _StubPage) -> None:
        self.id = tab_id
        self._page = page

    @property
    def url(self) -> str:
        return self._page.url

    def is_closed(self) -> bool:
        return self._page.is_closed()

    async def close(self) -> None:
        await self._page.close()

    async def render_document(
        self,
        response: Any = None,
        **kwargs: Any,
    ) -> RenderedDocument:
        return RenderedDocument(
            title="",
            url=self.url,
            status_code=200,
            content="",
            viewport={
                "scroll_top": 0,
                "viewport_height": 0,
                "viewport_width": 0,
                "document_height": 0,
            },
            truncated=False,
        )

    async def screenshot(self, **kwargs: Any) -> bytes:
        return b""


class _StubBrowser:
    """Browser stub modeling stable IDs + busy flag + open_pages."""

    def __init__(self) -> None:
        self._tabs: list[_StubTab] = []
        self._next_id = 0
        self._tabs_in_navigation: set[_StubTab] = set()

    # ── Tab tracking ──────────────────────────────────────────────────
    def open_pages(self) -> list[_StubPage]:
        return [tab._page for tab in self.tabs()]

    def tabs(self) -> list[_StubTab]:
        return [tab for tab in self._tabs if not tab.is_closed()]

    def get_tab(self, tab: Any) -> _StubTab:
        tabs = self.tabs()
        if not tabs:
            raise ValueError("No open tabs; call new_tab(url) first")
        target = int(str(tab).strip())
        for candidate in tabs:
            if candidate.id == target:
                return candidate
        raise ValueError(f"tab={tab!r} not found.")

    # ── Page / navigation surface ─────────────────────────────────────
    async def new_tab(self) -> _StubTab:
        page = _StubPage()
        self._next_id += 1
        tab = _StubTab(self._next_id, page)
        self._tabs.append(tab)
        return tab

    async def navigate(self, url: str, *, tab: _StubTab) -> ActionResult:
        if tab in self._tabs_in_navigation:
            raise BrowserToolError(
                f"Navigation already in flight on tab={tab.id}. Use new_tab(url).",
                tool="goto",
            )
        self._tabs_in_navigation.add(tab)
        try:
            tab._page.url = url
            return ActionResult(
                navigation_response=None,
                download=None,
                tab=tab,
            )
        finally:
            self._tabs_in_navigation.discard(tab)


@pytest.fixture
def stub_browser(monkeypatch: pytest.MonkeyPatch) -> _StubBrowser:
    browser = _StubBrowser()

    async def _get_browser() -> _StubBrowser:
        return browser

    async def _events_get_browser() -> _StubBrowser:
        return browser

    monkeypatch.setattr("tools.browser.navigation.get_browser", _get_browser)
    monkeypatch.setattr("tools.browser._tool_context.get_browser", _get_browser)
    monkeypatch.setattr("tools.browser.events.get_browser", _events_get_browser)
    return browser


@pytest.mark.unit
@pytest.mark.asyncio
async def test_goto_errors_when_no_tabs(stub_browser: _StubBrowser) -> None:
    """goto needs an existing tab — call new_tab first."""
    with pytest.raises(BrowserToolError, match="No open tabs"):
        await goto("https://example.com", tab="1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_goto_navigates_existing_tab(stub_browser: _StubBrowser) -> None:
    """goto re-points an existing tab in place."""
    await new_tab("https://example.com")
    await goto("https://other.com", tab="1")
    assert len(stub_browser.open_pages()) == 1
    assert stub_browser.open_pages()[0].url == "https://other.com"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_goto_with_tab_arg(stub_browser: _StubBrowser) -> None:
    """goto(url, tab='N') navigates that specific tab."""
    await new_tab("https://a.com")
    await new_tab("https://b.com")
    await goto("https://navigated.com", tab="1")
    tabs = stub_browser.open_pages()
    assert tabs[0].url == "https://navigated.com"
    assert tabs[1].url == "https://b.com"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_goto_unknown_tab_errors(stub_browser: _StubBrowser) -> None:
    await new_tab("https://a.com")
    with pytest.raises(BrowserToolError, match="tab='99' not found"):
        await goto("https://c.com", tab="99")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_new_tab_opens_new(stub_browser: _StubBrowser) -> None:
    await new_tab("https://a.com")
    out = await new_tab("https://b.com")
    assert len(stub_browser.open_pages()) == 2
    assert "tab=2" in out


@pytest.mark.unit
@pytest.mark.asyncio
async def test_close_tab_removes_tab(stub_browser: _StubBrowser) -> None:
    await new_tab("https://a.com")
    await new_tab("https://b.com")
    output = await close_tab(tab="1")
    assert output == "Closed tab=1."
    assert len(stub_browser.open_pages()) == 1
    assert stub_browser.open_pages()[0].url == "https://b.com"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_close_tab_id_not_reused(stub_browser: _StubBrowser) -> None:
    """After closing a tab, new tabs get fresh IDs — closed ID is not reused."""
    await new_tab("https://a.com")  # tab 1
    await new_tab("https://b.com")  # tab 2
    await close_tab(tab="1")
    output = await new_tab("https://c.com")  # should be tab 3, not tab 1
    assert "tab=3" in output


@pytest.mark.unit
@pytest.mark.asyncio
async def test_close_tab_errors_when_unknown(stub_browser: _StubBrowser) -> None:
    await new_tab("https://a.com")
    with pytest.raises(BrowserToolError, match="not found"):
        await close_tab(tab="42")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_parallel_goto_on_different_tabs_both_succeed(
    stub_browser: _StubBrowser,
) -> None:
    """Concurrent goto on different tabs do not race — each lands correctly.

    This is the user-facing capability the multi-tab redesign was for:
    the agent can drive multiple tabs in one batch without them
    clobbering each other.
    """
    await new_tab("https://a.com")  # tab=1
    await new_tab("https://b.com")  # tab=2

    a_out, b_out = await asyncio.gather(
        goto("https://navigated-a.com", tab="1"),
        goto("https://navigated-b.com", tab="2"),
    )

    tabs = stub_browser.open_pages()
    assert tabs[0].url == "https://navigated-a.com"
    assert tabs[1].url == "https://navigated-b.com"
    # Each result's header carries its own tab ID — no cross-contamination.
    assert "tab=1" in a_out
    assert "tab=2" in b_out
    assert "navigated-a.com" in a_out
    assert "navigated-b.com" in b_out
