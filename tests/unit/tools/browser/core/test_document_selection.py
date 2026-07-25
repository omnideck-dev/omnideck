"""Tests for selecting the document browser tools should use."""

from __future__ import annotations

from typing import Any

import pytest

from tools.browser.core.tab import Tab


class _FakeFrameElement:
    """Stub for the element returned by frame.frame_element()."""

    def __init__(self, box: dict[str, float] | None) -> None:
        self._box = box

    async def bounding_box(self) -> dict[str, float] | None:
        return self._box


class _FakeFrame:
    """Minimal Frame stub for _detect_embedded_content_frame tests."""

    def __init__(
        self,
        *,
        url: str = "https://iframe.test/widget",
        detached: bool = False,
        box: dict[str, float] | None = None,
        child_count: int = 5,
        cross_origin: bool = False,
    ) -> None:
        self.url = url
        self._detached = detached
        self._box = box
        self._child_count = child_count
        self._cross_origin = cross_origin
        self._element = _FakeFrameElement(box)

    def is_detached(self) -> bool:
        return self._detached

    async def frame_element(self) -> _FakeFrameElement:
        return self._element

    async def evaluate(self, script: str) -> Any:
        if self._cross_origin:
            raise Exception("Execution context was destroyed")
        # Content check used by _detect_embedded_content_frame
        if "interactive" in script:
            return {
                "children": self._child_count,
                "text": 100 if self._child_count > 0 else 0,
                "interactive": self._child_count,
            }
        return self._child_count


class _FakePage:
    """Minimal Page stub exposing frames and a measurable window size."""

    def __init__(
        self,
        *,
        frames: list[Any] | None = None,
        window: dict[str, int] | None = None,
    ) -> None:
        self.frames = frames or []
        # Production runs with no emulated viewport, so viewport_size is None;
        # detection measures the real window via evaluate() instead.
        self.viewport_size = None
        self._window = window or {"width": 1280, "height": 800}
        self.main_frame = object()
        # Prepend main_frame to the frames list so page.frames includes it
        self.frames.insert(0, self.main_frame)
        self.url = "https://example.test"

    async def evaluate(self, script: str) -> Any:
        # The only page-level evaluate() is the window-size measurement.
        return dict(self._window)

    def is_closed(self) -> bool:
        return False

    def on(self, event: str, callback: Any) -> None:
        pass


def _make_tab(page: _FakePage) -> Tab:
    return Tab(1, page)  # type: ignore[arg-type]


# ---- _detect_embedded_content_frame tests ----


@pytest.mark.unit
@pytest.mark.asyncio
async def test_detect_no_iframes_returns_none() -> None:
    """No iframes on page -> None."""
    page = _FakePage()
    result = await _make_tab(page)._detect_embedded_content_frame()
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_detect_large_iframe_returns_frame() -> None:
    """An iframe covering >25% of viewport is detected."""
    frame = _FakeFrame(box={"x": 0, "y": 0, "width": 1000, "height": 700})
    page = _FakePage(frames=[frame])
    result = await _make_tab(page)._detect_embedded_content_frame()
    assert result is frame


@pytest.mark.unit
@pytest.mark.asyncio
async def test_detect_small_iframe_returns_none() -> None:
    """An iframe smaller than 25% of viewport is ignored."""
    # Viewport is 1280x800 = 1_024_000.  25% = 256_000.
    # This frame is 200x200 = 40_000 — well below threshold.
    frame = _FakeFrame(box={"x": 10, "y": 10, "width": 200, "height": 200})
    page = _FakePage(frames=[frame])
    result = await _make_tab(page)._detect_embedded_content_frame()
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_detect_cross_origin_iframe_skipped() -> None:
    """Cross-origin iframe (evaluate throws) is skipped."""
    frame = _FakeFrame(
        box={"x": 0, "y": 0, "width": 1200, "height": 700},
        cross_origin=True,
    )
    page = _FakePage(frames=[frame])
    result = await _make_tab(page)._detect_embedded_content_frame()
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_detect_detached_iframe_skipped() -> None:
    """Detached iframe is skipped."""
    frame = _FakeFrame(
        box={"x": 0, "y": 0, "width": 1200, "height": 700},
        detached=True,
    )
    page = _FakePage(frames=[frame])
    result = await _make_tab(page)._detect_embedded_content_frame()
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_detect_empty_iframe_skipped() -> None:
    """Iframe with no children is skipped."""
    frame = _FakeFrame(
        box={"x": 0, "y": 0, "width": 1200, "height": 700},
        child_count=0,
    )
    page = _FakePage(frames=[frame])
    result = await _make_tab(page)._detect_embedded_content_frame()
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_detect_picks_largest_frame() -> None:
    """When multiple qualifying frames exist, the largest wins."""
    small = _FakeFrame(
        url="https://small.test",
        box={"x": 0, "y": 0, "width": 700, "height": 500},
    )
    large = _FakeFrame(
        url="https://large.test",
        box={"x": 0, "y": 0, "width": 1200, "height": 750},
    )
    page = _FakePage(frames=[small, large])
    result = await _make_tab(page)._detect_embedded_content_frame()
    assert result is large


# ---- document selection tests ----


@pytest.mark.unit
@pytest.mark.asyncio
async def test_document_selects_root_when_no_embedded_content() -> None:
    """The root document is selected when no embedded content qualifies."""
    page = _FakePage()
    result = await _make_tab(page).document()
    assert result._frame is page.main_frame


@pytest.mark.unit
@pytest.mark.asyncio
async def test_document_selects_cached_embedded_content() -> None:
    """A cached embedded content frame becomes the selected document."""
    page = _FakePage()
    frame = _FakeFrame()
    tab = _make_tab(page)
    tab._set_content_frame(frame)  # type: ignore[arg-type]
    result = await tab.document()
    assert result._frame is frame


@pytest.mark.unit
@pytest.mark.asyncio
async def test_document_falls_back_to_root_on_detach() -> None:
    """When the cached frame detaches, drop it and fall back to the page."""
    page = _FakePage()
    frame = _FakeFrame(detached=True)
    tab = _make_tab(page)
    tab._set_content_frame(frame)  # type: ignore[arg-type]
    result = await tab.document()
    assert result._frame is page.main_frame
    assert (await tab.document())._frame is page.main_frame


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invalidate_document() -> None:
    """Invalidating one tab leaves another tab's document untouched."""
    page = _FakePage()
    other_page = _FakePage()
    tab = _make_tab(page)
    other_tab = Tab(2, other_page)  # type: ignore[arg-type]
    frame = _FakeFrame()
    other_frame = _FakeFrame()
    tab._set_content_frame(frame)  # type: ignore[arg-type]
    other_tab._set_content_frame(other_frame)  # type: ignore[arg-type]
    tab._invalidate_document()
    assert (await tab.document())._frame is page.main_frame
    assert (await other_tab.document())._frame is other_frame


@pytest.mark.unit
@pytest.mark.asyncio
async def test_main_document_navigation_invalidates_selected_document() -> None:
    page = _FakePage()
    tab = _make_tab(page)
    tab._set_content_frame(_FakeFrame())  # type: ignore[arg-type]

    tab._handle_frame_navigated(page.main_frame)  # type: ignore[arg-type]

    assert (await tab.document())._frame is page.main_frame


@pytest.mark.unit
@pytest.mark.asyncio
async def test_only_selected_document_navigation_invalidates_selection() -> None:
    page = _FakePage()
    tab = _make_tab(page)
    selected = _FakeFrame()
    tab._set_content_frame(selected)  # type: ignore[arg-type]

    tab._handle_frame_navigated(_FakeFrame())  # type: ignore[arg-type]
    assert (await tab.document())._frame is selected

    tab._handle_frame_navigated(selected)  # type: ignore[arg-type]
    assert (await tab.document())._frame is page.main_frame


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unmeasurable_window_returns_none() -> None:
    """When the window size can't be measured (zero-sized), detection returns None."""
    frame = _FakeFrame(box={"x": 0, "y": 0, "width": 1200, "height": 700})
    page = _FakePage(frames=[frame], window={"width": 0, "height": 0})
    result = await _make_tab(page)._detect_embedded_content_frame()
    assert result is None
