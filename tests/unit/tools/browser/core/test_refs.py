"""Tests for browser element-ref resolution."""

from __future__ import annotations

import pytest

from tests.unit.tools.browser.support.playwright_stubs import StubPage
from tools.browser.core.document import Document
from tools.browser.core.exceptions import BrowserToolError


@pytest.mark.asyncio
async def test_duplicate_ref_is_rejected() -> None:
    """A ref must never silently choose between multiple matching elements."""
    page = StubPage()
    page.add_ref_locator(1, texts=["stale", "current"])
    document = Document(frame=page, page=page)

    with pytest.raises(BrowserToolError, match="Ref 1 matched 2 elements"):
        await document.resolve_ref("1", tool_name="click")
