"""Tests for browser vision tools (inspect_page + browser_visual_action)."""

from __future__ import annotations

import base64
import importlib

import pytest

from browser.core.document import Document
from browser.core.rendering import RenderedDocument
from tools._grounding import GroundingResponse
from tools.browser import BrowserToolError
from tools.browser.vision import browser_visual_action, inspect_page

# ── Shared helpers ────────────────────────────────────────────────────


def _make_fake_get_document(browser):
    """Build a fake document resolver from a ``_FakeBrowser``."""

    async def _fake(tool_name, *, tab=None):
        resolved_tab = browser.get_tab(tab)
        if resolved_tab.url in {"", "about:blank"}:
            raise BrowserToolError("Navigate to a page first.", tool=tool_name)
        return browser, resolved_tab, await resolved_tab.document()

    return _fake


class _ScreenshotFakeLocator:
    def __init__(self, screenshot_bytes: bytes, exists: bool = True) -> None:
        self._screenshot_bytes = screenshot_bytes
        self._exists = exists
        self.first = self

    async def count(self) -> int:
        return 1 if self._exists else 0

    async def screenshot(self, *, type: str = "png") -> bytes:
        assert type == "png"
        if not self._exists:
            raise AssertionError("Should not capture screenshot when locator does not exist")
        return self._screenshot_bytes


class _ScreenshotFakePage:
    def __init__(
        self,
        screenshot_bytes: bytes,
        *,
        url: str = "https://example.com",
        locator_map: dict[str, _ScreenshotFakeLocator] | None = None,
    ) -> None:
        self._screenshot_bytes = screenshot_bytes
        self._locator_map = locator_map or {}
        self.url = url
        self.viewport_size = {"width": 1024, "height": 768}

    async def screenshot(self, *, full_page: bool = False, type: str = "png") -> bytes:
        assert type == "png"
        return self._screenshot_bytes

    async def evaluate(self, script: str, arg: object = None) -> str | dict:
        return ""

    def locator(self, selector: str) -> _ScreenshotFakeLocator:
        return self._locator_map.get(selector, _ScreenshotFakeLocator(b"", exists=False))

    def get_by_text(self, value: str, exact: bool = True) -> _ScreenshotFakeLocator:
        return _ScreenshotFakeLocator(b"", exists=False)

    def get_by_alt_text(self, value: str, exact: bool = True) -> _ScreenshotFakeLocator:
        return _ScreenshotFakeLocator(b"", exists=False)


class _FakeTab:
    def __init__(self, page: _ScreenshotFakePage) -> None:
        self._page = page
        self.id = 1
        self.challenge = None
        self._snapshot: RenderedDocument | None = None

    @property
    def url(self) -> str:
        return self._page.url

    async def document(self) -> Document:
        return Document(frame=self._page, page=self._page)

    async def screenshot(self, *, full_page: bool = False, **kwargs) -> bytes:
        return await self._page.screenshot(full_page=full_page)

    async def render_document(self, **kwargs):
        return self._snapshot or RenderedDocument(
            title="Example",
            url=self.url,
            status_code=200,
            content="",
            viewport=None,
            truncated=False,
        )


class _FakeBrowser:
    def __init__(self, page: _ScreenshotFakePage) -> None:
        self._tab = _FakeTab(page)

    def get_tab(self, tab):
        return self._tab

    async def coordinate_action(self, action_fn, *, source_tab=None):
        from browser.core.browser import ActionResult

        await action_fn()
        return ActionResult(
            action_ms=10.0,
            navigation_response=None,
            tab=source_tab,
        )


_FAKE_SETTINGS = {
    "vision_model": "vision-model",
    "vision_options": {"temperature": 0.0},
    "vision_think": False,
}


async def _fake_vision_generate(prompt, image_base64, *, media_type="image/png"):
    """Stand-in for sdk.providers.vision_generate."""
    _fake_vision_generate.called = True
    _fake_vision_generate.last_prompt = prompt
    _fake_vision_generate.last_image = image_base64
    return "Mock answer"


_fake_vision_generate.called = False
_fake_vision_generate.last_prompt = None
_fake_vision_generate.last_image = None


# ── inspect_page tests ────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_inspect_page_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """inspect_page should capture a screenshot and forward it to the provider."""
    from unittest.mock import patch

    page = _ScreenshotFakePage(b"fake-image-bytes")
    browser = _FakeBrowser(page)

    _fake_vision_generate.called = False
    _fake_vision_generate.last_prompt = None
    _fake_vision_generate.last_image = None

    module = importlib.import_module("tools.browser.vision")
    import settings as settings_module

    monkeypatch.setattr(module, "get_document", _make_fake_get_document(browser))
    monkeypatch.setattr(settings_module, "load_settings", lambda: dict(_FAKE_SETTINGS))

    with patch("sdk.providers.vision_generate", _fake_vision_generate):
        answer = await inspect_page("What is in the header?", tab="1")

    assert answer == "Mock answer"
    assert _fake_vision_generate.called
    assert _fake_vision_generate.last_prompt == "What is in the header?"
    encoded = base64.b64encode(b"fake-image-bytes").decode("ascii")
    assert _fake_vision_generate.last_image == encoded


@pytest.mark.unit
@pytest.mark.asyncio
async def test_inspect_page_rejects_blank_prompt() -> None:
    """Blank prompts should raise a BrowserToolError."""
    with pytest.raises(BrowserToolError):
        await inspect_page("   ", tab="1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_inspect_page_requires_navigation(monkeypatch: pytest.MonkeyPatch) -> None:
    """inspect_page should require a navigated page."""
    page = _ScreenshotFakePage(b"img", url="about:blank")
    browser = _FakeBrowser(page)

    async def fake_get_browser() -> _FakeBrowser:
        return browser

    module = importlib.import_module("tools.browser.vision")

    monkeypatch.setattr(module, "get_document", _make_fake_get_document(browser))

    with pytest.raises(BrowserToolError):
        await inspect_page("Describe the page", tab="1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_inspect_page_ref_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ref screenshots should focus on the requested element."""
    from unittest.mock import patch

    locator = _ScreenshotFakeLocator(b"element-bytes")
    page = _ScreenshotFakePage(
        b"page-bytes",
        locator_map={'[data-ct-ref="7"]': locator},
    )
    browser = _FakeBrowser(page)

    _fake_vision_generate.called = False
    _fake_vision_generate.last_image = None

    module = importlib.import_module("tools.browser.vision")
    import settings as settings_module

    async def _get_browser():
        return browser

    monkeypatch.setattr(module, "get_document", _make_fake_get_document(browser))
    monkeypatch.setattr(settings_module, "load_settings", lambda: dict(_FAKE_SETTINGS))

    with patch("sdk.providers.vision_generate", _fake_vision_generate):
        answer = await inspect_page("Describe the hero", mode="ref", ref="7", tab="1")

    assert answer == "Mock answer"
    assert _fake_vision_generate.called
    assert _fake_vision_generate.last_image == base64.b64encode(b"element-bytes").decode("ascii")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ref_mode_requires_non_empty_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ref mode should reject an empty ref."""
    page = _ScreenshotFakePage(b"page")
    browser = _FakeBrowser(page)

    async def fake_get_browser() -> _FakeBrowser:
        return browser

    module = importlib.import_module("tools.browser.vision")
    monkeypatch.setattr(module, "get_document", _make_fake_get_document(browser))

    with pytest.raises(BrowserToolError):
        await inspect_page("prompt", mode="ref", ref="   ", tab="1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ref_mode_missing_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing ref should raise a clear error message."""
    page = _ScreenshotFakePage(b"page")
    browser = _FakeBrowser(page)

    async def fake_get_browser() -> _FakeBrowser:
        return browser

    module = importlib.import_module("tools.browser.vision")
    monkeypatch.setattr(module, "get_document", _make_fake_get_document(browser))

    with pytest.raises(BrowserToolError) as excinfo:
        await inspect_page("Anything", mode="ref", ref="99", tab="1")

    msg = str(excinfo.value)
    assert "Ref 99 not found" in msg


# ── browser_visual_action tests ───────────────────────────────────────


_CLICK_GROUNDING_RESPONSE = GroundingResponse(
    x=500,
    y=300,
    thought="Found the login button",
    action_type="click",
    raw={"x": 500, "y": 300, "coordinates": [{"screen": [500, 300]}]},
)

_TYPE_GROUNDING_RESPONSE = GroundingResponse(
    x=None,
    y=None,
    thought="Need to type text",
    action_type="type",
    raw={"type_content": "hello world"},
)

_FINISHED_GROUNDING_RESPONSE = GroundingResponse(
    x=None,
    y=None,
    thought="Done",
    action_type="finished",
    raw={"finished_content": "Login was successful"},
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_browser_visual_action_click(monkeypatch: pytest.MonkeyPatch) -> None:
    """browser_visual_action with a click response should execute the click."""
    page = _ScreenshotFakePage(b"fake-bytes")
    browser = _FakeBrowser(page)

    module = importlib.import_module("tools.browser.vision")
    grounding_module = importlib.import_module("tools._grounding")

    monkeypatch.setattr(module, "get_document", _make_fake_get_document(browser))

    async def fake_run_grounding(screenshot_bytes, task, *, screenshot_filename=""):
        return _CLICK_GROUNDING_RESPONSE

    monkeypatch.setattr(grounding_module, "run_grounding", fake_run_grounding)

    # Mock execute_action to avoid needing real Playwright
    from unittest.mock import AsyncMock

    mock_execute = AsyncMock()
    monkeypatch.setattr("tools.browser._visual_actions.execute_action", mock_execute)

    # Mock format_action_result — patch the name bound in the vision module.
    async def fake_format_action_result(result, *, tool_name, resolution=None):
        return "[page snapshot]"

    monkeypatch.setattr(module, "format_action_result", fake_format_action_result)

    result = await browser_visual_action("Click the login button", tab="1")
    assert isinstance(result, str)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_browser_visual_action_finished(monkeypatch: pytest.MonkeyPatch) -> None:
    """browser_visual_action with finished response should return snapshot with note."""
    page = _ScreenshotFakePage(b"fake-bytes")
    browser = _FakeBrowser(page)

    module = importlib.import_module("tools.browser.vision")
    grounding_module = importlib.import_module("tools._grounding")

    monkeypatch.setattr(module, "get_document", _make_fake_get_document(browser))

    async def fake_run_grounding(screenshot_bytes, task, *, screenshot_filename=""):
        return _FINISHED_GROUNDING_RESPONSE

    monkeypatch.setattr(grounding_module, "run_grounding", fake_run_grounding)

    fake_snapshot = RenderedDocument(
        title="Test Page",
        url="https://example.com",
        status_code=200,
        content="Page content here",
        viewport=None,
        truncated=False,
        node_count=0,
        dom_walk_ms=0.0,
        render_ms=0.0,
    )

    browser._tab._snapshot = fake_snapshot

    result = await browser_visual_action("Check if login succeeded", tab="1")
    assert "finished" in result.lower() or "Login was successful" in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_browser_visual_action_empty_task() -> None:
    """Empty task should raise BrowserToolError."""
    with pytest.raises(BrowserToolError):
        await browser_visual_action("   ", tab="1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_browser_visual_action_grounding_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """RuntimeError from grounding should become BrowserToolError."""
    page = _ScreenshotFakePage(b"fake")
    browser = _FakeBrowser(page)

    module = importlib.import_module("tools.browser.vision")
    grounding_module = importlib.import_module("tools._grounding")

    monkeypatch.setattr(module, "get_document", _make_fake_get_document(browser))

    async def failing_grounding(*args, **kwargs):
        raise RuntimeError("Grounding failed: container not running")

    monkeypatch.setattr(grounding_module, "run_grounding", failing_grounding)

    with pytest.raises(BrowserToolError, match="Grounding request failed"):
        await browser_visual_action("Click login", tab="1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_browser_visual_action_requires_navigation(monkeypatch: pytest.MonkeyPatch) -> None:
    """browser_visual_action should require a navigated page."""
    page = _ScreenshotFakePage(b"bytes", url="about:blank")
    browser = _FakeBrowser(page)
    module = importlib.import_module("tools.browser.vision")

    monkeypatch.setattr(module, "get_document", _make_fake_get_document(browser))

    with pytest.raises(BrowserToolError):
        await browser_visual_action("Click login", tab="1")
