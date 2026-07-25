from __future__ import annotations

import pytest

from tests.unit.tools.browser.support.playwright_stubs import StubPage
from tools.browser.navigation import go_back


@pytest.mark.unit
@pytest.mark.asyncio
async def test_go_back_navigates_backward(
    browser_tool_harness,
    settle_tracker,
) -> None:
    page = StubPage(
        title="Start",
        body_text="Start body",
        url="https://example.test/start",
    )
    page._apply_navigation(
        url="https://example.test/next",
        title="Next",
        body="Next body",
    )
    browser_tool_harness(page)

    result = await go_back(tab="1")
    assert isinstance(result, str)
    assert "[Page:" in result
    assert "https://example.test/start" in result
    assert "Start body" in result
    assert settle_tracker["count"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_go_back_no_history_returns_snapshot(browser_tool_harness) -> None:
    """When there is no history, go_back still returns a snapshot instead of raising."""
    page = StubPage(
        title="Only",
        body_text="Body",
        url="https://example.test/only",
    )
    browser_tool_harness(page)

    result = await go_back(tab="1")
    assert isinstance(result, str)
    assert "Only" in result
