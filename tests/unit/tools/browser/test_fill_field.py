"""Unit tests for the fill_field browser interaction tool."""

from __future__ import annotations

import pytest

from browser.core.document import Document, ResolvedElement
from tests.unit.tools.browser.support.playwright_stubs import StubPage
from tools.browser import BrowserToolError
from tools.browser.interactions import fill_field


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fill_field_by_ref(
    monkeypatch: pytest.MonkeyPatch,
    browser_tool_harness,
    settle_tracker,
) -> None:
    """Locates the input field by ref number."""
    page = StubPage(
        title="Initial",
        body_text="Before fill",
        url="https://example.test/form",
    )
    locator = page.add_ref_locator(1, tag="input")
    browser_tool_harness(page)

    async def fill_passthrough(
        document: Document,
        element: ResolvedElement,
        value: str,
    ) -> None:
        assert element.ref == "1"
        await locator.fill("")
        await locator.type(value)

    monkeypatch.setattr(Document, "fill_field", fill_passthrough)

    result = await fill_field("1", "user@example.com", tab="1")
    assert "[Page:" in result
    assert settle_tracker["count"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fill_field_rejects_checkbox(
    monkeypatch: pytest.MonkeyPatch,
    browser_tool_harness,
) -> None:
    """Rejects unsupported input types such as checkbox."""
    page = StubPage(
        title="Initial",
        body_text="Before fill",
        url="https://example.test/form",
    )
    page.add_ref_locator(1, tag="input", input_type="checkbox")
    browser_tool_harness(page)

    with pytest.raises(BrowserToolError):
        await fill_field("1", True, tab="1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fill_field_requires_non_empty_ref(
    monkeypatch: pytest.MonkeyPatch,
    browser_tool_harness,
) -> None:
    """Rejects a whitespace-only ref."""
    page = StubPage(
        title="Initial",
        body_text="Before fill",
        url="https://example.test/form",
    )
    browser_tool_harness(page)

    with pytest.raises(BrowserToolError):
        await fill_field("   ", "value", tab="1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fill_field_select_element(
    monkeypatch: pytest.MonkeyPatch,
    browser_tool_harness,
) -> None:
    """Raising error for select elements which are no longer supported."""
    page = StubPage(
        title="Initial",
        body_text="Before fill",
        url="https://example.test/form",
    )
    page.add_ref_locator(1, tag="select")
    browser_tool_harness(page)

    with pytest.raises(BrowserToolError):
        await fill_field("1", "us", tab="1")
