from __future__ import annotations

import pytest

from browser.core.document import Document
from tests.unit.tools.browser.support.playwright_stubs import StubPage
from tools.browser import BrowserToolError
from tools.browser.interactions import press_keys


class FakeKeyboard:
    def __init__(self) -> None:
        self.pressed: list[str] = []

    async def press(self, key: str) -> None:
        self.pressed.append(f"press:{key}")

    async def down(self, key: str) -> None:
        self.pressed.append(f"down:{key}")

    async def up(self, key: str) -> None:
        self.pressed.append(f"up:{key}")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_press_keys_success(
    monkeypatch: pytest.MonkeyPatch,
    browser_tool_harness,
    settle_tracker,
) -> None:
    keyboard = FakeKeyboard()
    page = StubPage(
        title="Initial",
        body_text="Before press",
        url="https://example.test/start",
    )
    page.keyboard = keyboard  # type: ignore[attr-defined]
    browser_tool_harness(page)

    async def fake_press_keys(document: Document, keys: list[str]) -> None:
        for k in keys:
            await keyboard.press(k)

    monkeypatch.setattr(Document, "press_keys", fake_press_keys)

    result = await press_keys(["Enter"], tab="1")
    assert isinstance(result, str)
    assert "[Page:" in result
    assert settle_tracker["count"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_press_keys_invalid_input() -> None:
    with pytest.raises(BrowserToolError):
        await press_keys([], tab="1")
