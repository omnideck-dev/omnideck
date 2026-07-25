"""Unit tests for the press_and_hold browser interaction tool."""

from __future__ import annotations

import pytest

from tests.unit.tools.browser.support.playwright_stubs import StubPage
from tools.browser import BrowserToolError
from tools.browser.core.document import Document, ResolvedElement
from tools.browser.interactions import press_and_hold


async def _human_press_and_hold_passthrough(
    document: Document,
    element: ResolvedElement,
    *,
    duration_ms: int,
) -> None:
    """Record a successful Document-level press without physical input."""
    assert element.ref.isdecimal()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_press_and_hold_basic(
    monkeypatch: pytest.MonkeyPatch,
    browser_tool_harness,
    settle_tracker,
) -> None:
    """Pressing and holding a role-matched element returns a valid snapshot."""
    page = StubPage(
        title="Bot Challenge",
        body_text="Press and hold to verify",
        url="https://example.test/challenge",
    )
    page.add_ref_locator(1, tag="button")
    browser_tool_harness(page)
    monkeypatch.setattr(Document, "press_and_hold", _human_press_and_hold_passthrough)

    result = await press_and_hold("1", duration_ms=3000, tab="1")
    assert isinstance(result, str)
    assert "[Page:" in result
    assert settle_tracker["count"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_press_and_hold_empty_ref(
    browser_tool_harness,
) -> None:
    """An empty ref raises BrowserToolError before accessing the browser."""
    page = StubPage(url="https://example.test/page")
    browser_tool_harness(page)

    with pytest.raises(BrowserToolError, match="non-empty"):
        await press_and_hold("   ", tab="1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_press_and_hold_about_blank(
    monkeypatch: pytest.MonkeyPatch,
    browser_tool_harness,
) -> None:
    """Pressing on about:blank raises a helpful error."""
    page = StubPage(url="about:blank", body_text="")
    browser_tool_harness(page)

    with pytest.raises(BrowserToolError, match="Navigate"):
        await press_and_hold("1", tab="1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_press_and_hold_not_found(
    monkeypatch: pytest.MonkeyPatch,
    browser_tool_harness,
) -> None:
    """Raises BrowserToolError when element can't be located."""
    page = StubPage(
        title="Challenge",
        body_text="Page content",
        url="https://example.test/challenge",
    )
    browser_tool_harness(page)

    with pytest.raises(BrowserToolError):
        await press_and_hold("99", tab="1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_press_and_hold_duration_clamped(
    monkeypatch: pytest.MonkeyPatch,
    browser_tool_harness,
    settle_tracker,
) -> None:
    """Duration is clamped to 500-10000 range and passed to human helper."""
    captured_durations: list[int] = []

    async def _capture_duration(
        document: Document,
        element: ResolvedElement,
        *,
        duration_ms: int,
    ) -> None:
        captured_durations.append(duration_ms)

    page = StubPage(
        title="Challenge",
        body_text="Hold button",
        url="https://example.test/challenge",
    )
    page.add_ref_locator(1, tag="button")
    browser_tool_harness(page)
    monkeypatch.setattr(Document, "press_and_hold", _capture_duration)

    # Below minimum: should clamp to 500
    await press_and_hold("1", duration_ms=100, tab="1")
    assert captured_durations[-1] == 500

    # Above maximum: should clamp to 10000
    await press_and_hold("1", duration_ms=99999, tab="1")
    assert captured_durations[-1] == 10000

    # Within range: should pass through
    await press_and_hold("1", duration_ms=5000, tab="1")
    assert captured_durations[-1] == 5000
