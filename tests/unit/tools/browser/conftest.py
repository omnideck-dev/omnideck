"""Shared pytest fixtures for browser tool tests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from browser.core.browser import ActionResult
from browser.core.document import Document
from browser.core.rendering import DEFAULT_BUDGET
from browser.core.rendering import render_document as render
from config import load_config


class _StubTab:
    """Small public-surface stand-in for a browser ``Tab``."""

    def __init__(self, page: Any) -> None:
        self.id = 1
        self._page = page
        self._document = Document(frame=page, page=page)

    @property
    def url(self) -> str:
        return self._page.url

    @property
    def challenge(self) -> None:
        return None

    async def title(self) -> str:
        try:
            return await self._page.title()
        except Exception:
            return "Test Page"

    async def document(self) -> Document:
        return self._document

    async def render_document(
        self,
        response: Any = None,
        **kwargs: Any,
    ) -> Any:
        document = await self.document()
        waits = load_config().tools.browser.waits
        timings = await document.settle(waits) if kwargs.get("settle", True) else None
        return await render(
            self,
            document,
            response,
            scope=kwargs.get("scope"),
            budget=kwargs.get("budget", DEFAULT_BUDGET),
            full_page=kwargs.get("full_page", False),
            settle_timings=timings,
        )

    def is_closed(self) -> bool:
        return bool(getattr(self._page, "is_closed", lambda: False)())

    async def screenshot(self, **kwargs: Any) -> bytes:
        return await self._page.screenshot(**kwargs)


class _StubBrowser:
    """Minimal Browser-shaped coordinator for interaction tool tests."""

    def __init__(self, page: Any) -> None:
        self._page = page
        self._tab = _StubTab(page)

    async def navigate_back(self, tab: _StubTab) -> ActionResult:
        async def _back() -> None:
            await self._page.go_back(wait_until="domcontentloaded")

        return await self.coordinate_action(_back, source_tab=tab)

    def get_tab(self, tab: Any) -> _StubTab:
        del tab
        return self._tab

    async def coordinate_action(
        self,
        action: Callable[[], Awaitable[Any]],
        *,
        source_tab: _StubTab,
        wait_for_navigation: bool = True,
    ) -> ActionResult:
        """Run an action while leaving settling to the render-return boundary."""
        del wait_for_navigation
        await action()
        return ActionResult(
            navigation_response=None,
            tab=source_tab,
        )


@pytest.fixture(autouse=True)
def _reset_scroll_budget() -> None:
    """Reset scroll budget tracking between tests."""
    from tools.browser.interactions import _scroll_count_var, _scroll_url_var

    _scroll_count_var.set(0)
    _scroll_url_var.set("")


@pytest.fixture
def browser_tool_harness(monkeypatch: pytest.MonkeyPatch) -> Callable[[Any], _StubBrowser]:
    """Connect agent-tool modules to a browser test double.

    Also patches ``tools.browser.events.get_browser`` so the
    ``emit_screenshot_after`` decorator does not try to launch a
    real Playwright browser when capturing post-interaction screenshots.

    Returns a callable so individual tests can supply their own fake page objects while
    reusing the same patching logic.
    """

    def _apply(page: Any) -> _StubBrowser:
        browser = _StubBrowser(page)

        async def _get_document(
            tool_name: str,
            *,
            tab: Any = None,
        ) -> tuple[_StubBrowser, _StubTab, Document]:
            from browser.core.exceptions import BrowserToolError

            resolved_tab = browser.get_tab(tab)
            if resolved_tab.url in {"", "about:blank"}:
                raise BrowserToolError("Navigate to a page first.", tool=tool_name)
            return browser, resolved_tab, await resolved_tab.document()

        async def _events_get_browser() -> _StubBrowser:
            return browser

        monkeypatch.setattr("tools.browser.interactions.get_document", _get_document)
        monkeypatch.setattr("tools.browser.navigation.get_document", _get_document)
        monkeypatch.setattr("tools.browser.events.get_browser", _events_get_browser)
        return browser

    return _apply


@pytest.fixture
def settle_tracker(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Intercept document settling and record invocation metadata."""

    calls: dict[str, Any] = {"count": 0}

    async def _fake_settle(document: Document, waits: Any) -> Any:
        from browser.core.settling import SettleTimings

        calls["count"] += 1
        return SettleTimings()

    monkeypatch.setattr(Document, "settle", _fake_settle)
    return calls
