from __future__ import annotations

import pytest

from tests.unit.tools.browser.support.playwright_stubs import StubPage
from tools.browser.core.document import Document, ResolvedElement
from tools.browser.interactions import click


@pytest.mark.unit
@pytest.mark.asyncio
async def test_click_by_ref(
    monkeypatch: pytest.MonkeyPatch,
    browser_tool_harness,
    settle_tracker,
) -> None:
    """Clicking by ref number performs navigation and returns a snapshot."""

    page = StubPage(
        title="Initial",
        body_text="Before click",
        url="https://example.test/start",
    )
    locator = page.add_ref_locator(
        1,
        navigates_to="https://example.test/after",
        navigation_title="After Click",
        navigation_body="Arrived after navigation",
    )
    browser_tool_harness(page)

    async def click_passthrough(
        document: Document,
        element: ResolvedElement,
    ) -> None:
        assert element.ref == "1"
        await locator.click()

    monkeypatch.setattr(Document, "click", click_passthrough)

    result = await click("1", tab="1")
    assert isinstance(result, str)
    assert "[Page:" in result
    assert "https://example.test/after" in result
    assert "After Click" in result
    assert "Arrived" in result
    assert settle_tracker["count"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_click_ref_not_found(
    monkeypatch: pytest.MonkeyPatch,
    browser_tool_harness,
) -> None:
    """Returns error when ref number doesn't exist on the page."""
    page = StubPage(
        title="Cart",
        body_text="Shopping Cart",
        url="https://example.test/cart",
    )
    browser_tool_harness(page)
    result = await click("99", tab="1")
    assert "Ref 99 not found" in result
