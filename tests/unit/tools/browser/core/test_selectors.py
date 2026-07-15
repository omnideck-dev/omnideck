"""Tests for browser ref-to-locator resolution."""

from __future__ import annotations

import pytest

from tests.unit.tools.browser.support.playwright_stubs import StubPage
from tools.browser.core._selectors import _resolve_locator
from tools.browser.core.exceptions import BrowserToolError


@pytest.mark.asyncio
async def test_duplicate_ref_is_rejected() -> None:
    """A ref must never silently choose between multiple matching elements."""
    page = StubPage()
    page.add_ref_locator(1, texts=["stale", "current"])

    with pytest.raises(BrowserToolError, match="Ref 1 matched 2 elements"):
        await _resolve_locator(page, "1", tool_name="click")
