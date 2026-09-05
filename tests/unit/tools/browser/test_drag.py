from __future__ import annotations

import pytest

from browser.core.document import Document, ResolvedElement
from tests.unit.tools.browser.support.playwright_stubs import StubPage
from tools.browser import BrowserToolError
from tools.browser.interactions import drag


@pytest.mark.unit
@pytest.mark.asyncio
async def test_drag_delegates_to_document(
    monkeypatch: pytest.MonkeyPatch,
    browser_tool_harness,
    settle_tracker,
) -> None:
    page = StubPage(
        title="Drag Playground",
        body_text="Welcome to the drag playground.",
        url="https://example.test/drag",
    )
    page.drag_calls = []  # type: ignore[attr-defined]
    page.add_ref_locator(1)
    page.add_ref_locator(2)

    browser_tool_harness(page)

    async def record_drag(
        document: Document,
        source: ResolvedElement,
        target: ResolvedElement,
    ) -> None:
        page.drag_calls.append(  # type: ignore[attr-defined]
            {"source_ref": source.ref, "target_ref": target.ref}
        )

    monkeypatch.setattr(Document, "drag", record_drag)

    result = await drag("1", "2", tab="1")
    assert isinstance(result, str)
    assert "[Page:" in result
    assert page.drag_calls == [{"source_ref": "1", "target_ref": "2"}]
    assert settle_tracker["count"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_drag_with_ref(
    monkeypatch: pytest.MonkeyPatch,
    browser_tool_harness,
    settle_tracker,
) -> None:
    page = StubPage(
        title="Drag Playground",
        body_text="Welcome to the drag playground.",
        url="https://example.test/drag",
    )
    page.drag_calls = []  # type: ignore[attr-defined]
    page.add_ref_locator(1)
    page.add_ref_locator(2)

    browser_tool_harness(page)

    async def record_drag(
        document: Document,
        source: ResolvedElement,
        target: ResolvedElement,
    ) -> None:
        page.drag_calls.append(  # type: ignore[attr-defined]
            {"source_ref": source.ref, "target_ref": target.ref}
        )

    monkeypatch.setattr(Document, "drag", record_drag)

    result = await drag("1", "2", tab="1")
    assert "[Page:" in result
    assert page.drag_calls == [{"source_ref": "1", "target_ref": "2"}]
    assert settle_tracker["count"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_drag_empty_source(
    browser_tool_harness,
) -> None:
    page = StubPage(
        title="Drag Playground",
        body_text="Welcome to the drag playground.",
        url="https://example.test/drag",
    )
    browser_tool_harness(page)

    with pytest.raises(BrowserToolError):
        await drag("", "1", tab="1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_drag_empty_target(
    browser_tool_harness,
) -> None:
    page = StubPage(
        title="Drag Playground",
        body_text="Welcome to the drag playground.",
        url="https://example.test/drag",
    )
    page.add_ref_locator(1)
    browser_tool_harness(page)

    with pytest.raises(BrowserToolError):
        await drag("1", "", tab="1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_drag_target_not_found(
    browser_tool_harness,
) -> None:
    page = StubPage(
        title="Drag Playground",
        body_text="Welcome to the drag playground.",
        url="https://example.test/drag",
    )
    page.add_ref_locator(1)
    browser_tool_harness(page)

    with pytest.raises(BrowserToolError):
        await drag("1", "99", tab="1")
