"""Downloads and ordinary pages that arrive in a tab the site opened.

A click can open a tab (``target="_blank"``, ``window.open``).  What lands in
it is either a file, which is a download, or an ordinary page, which is simply
where the agent now is.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from playwright.async_api import Error as PlaywrightError

from browser.core.browser import Browser
from tests.unit.tools.browser.support.playwright_stubs import EventEmitterStub

# ---------------------------------------------------------------------------
# Stubs with event support
# ---------------------------------------------------------------------------


class FakePage(EventEmitterStub):
    """Stub page with event support."""

    def __init__(self, url: str = "https://old.example.com", closed: bool = False) -> None:
        super().__init__()
        self._closed = closed
        self.url = url
        self.main_frame = MagicMock()

    def is_closed(self) -> bool:
        return self._closed

    async def close(self) -> None:
        self._closed = True
        self.emit("close", self)

    async def set_viewport_size(self, size: dict[str, int]) -> None:
        return None

    async def wait_for_load_state(self, state: str, timeout: int = 30000) -> None:
        return None


class FakeResponse:
    """Document/API response with the file-saving surface Browser uses."""

    def __init__(
        self,
        *,
        url: str,
        content_type: str = "text/html",
        body: bytes = b"<html></html>",
        frame: object | None = None,
    ) -> None:
        self.url = url
        self.headers = {"content-type": content_type}
        self.request = MagicMock(resource_type="document")
        self.frame = frame
        self._body = body

    async def body(self) -> bytes:
        return self._body

    async def dispose(self) -> None:
        return None


class FakeRequestContext:
    """Return ordinary HTML when Browser probes an unannounced popup URL."""

    async def get(self, url: str) -> FakeResponse:
        return FakeResponse(url=url)


class FakeContext(EventEmitterStub):
    """Stub context with event support."""

    def __init__(self, pages: list[FakePage] | None = None) -> None:
        super().__init__()
        self.pages = pages or []
        self.request = FakeRequestContext()

    async def new_page(self) -> FakePage:
        page = FakePage()
        self.pages.append(page)
        self.emit("page", page)
        return page

    def open_tab(self, page: FakePage) -> None:
        """Simulate a click opening a tab (target=_blank)."""
        self.pages.append(page)
        self.emit("page", page)


def _make_browser(ctx: FakeContext, *, downloads_dir: str = "") -> Browser:
    return Browser(  # type: ignore[arg-type]
        context=ctx,
        extra_headers={},
        downloads_dir=downloads_dir,
    )


def _fake_response(
    *,
    url: str,
    content_type: str = "text/html",
    frame: object | None = None,
    body: bytes = b"<html></html>",
) -> FakeResponse:
    return FakeResponse(
        url=url,
        content_type=content_type,
        frame=frame,
        body=body,
    )


@pytest.mark.unit
class TestContextPageHandler:
    """Verify that context pages become public browser tabs."""

    def test_existing_pages_are_attached(self) -> None:
        """Pages that existed before Browser init become fully tracked tabs."""
        existing = FakePage()
        ctx = FakeContext([existing])
        browser = _make_browser(ctx)

        assert browser.tabs()[0].id == 1


@pytest.mark.unit
@pytest.mark.asyncio
class TestCoordinateActionNewTab:
    """Verify that coordinate_action detects files opened in new tabs."""

    async def test_pdf_in_new_tab_detected_via_response(self, tmp_path: Path) -> None:
        """A PDF response becomes a download and returns to the source tab."""
        old_page = FakePage(url="https://texas.gov/rules")
        ctx = FakeContext([old_page])
        browser = _make_browser(ctx, downloads_dir=str(tmp_path))

        pdf_response = _fake_response(
            url="https://texas.gov/rules.pdf",
            content_type="application/pdf",
            body=b"%PDF-1.4 fake pdf content",
        )
        new_page = FakePage(url="https://texas.gov/rules.pdf")

        async def fake_click() -> None:
            ctx.open_tab(new_page)
            new_page.emit("response", pdf_response)

        source_tab = browser.get_tab(1)
        result = await browser.coordinate_action(
            fake_click,
            source_tab=source_tab,
            wait_for_navigation=False,
        )

        assert result.download is not None
        assert result.download.filename == "rules.pdf"
        assert result.download.content_type == "application/pdf"
        assert result.navigation_response is pdf_response
        assert result.tab is source_tab
        assert new_page.is_closed()

    async def test_download_event_in_new_tab_detected(self, tmp_path: Path) -> None:
        """Click opening a PDF in a new tab is detected via download event."""
        old_page = FakePage(url="https://texas.gov/rules")
        ctx = FakeContext([old_page])
        browser = _make_browser(ctx, downloads_dir=str(tmp_path))

        new_page = FakePage(url="about:blank")
        opaque_path = tmp_path / "download-uuid"
        opaque_path.write_bytes(b"%PDF-1.4 fake pdf content")
        download = AsyncMock()
        download.path = AsyncMock(return_value=str(opaque_path))
        download.suggested_filename = "rules.pdf"

        async def fake_click() -> None:
            ctx.open_tab(new_page)
            new_page.emit("download", download)

        source_tab = browser.get_tab(1)
        result = await browser.coordinate_action(
            fake_click,
            source_tab=source_tab,
            wait_for_navigation=False,
        )

        assert result.download is not None
        assert result.download.filename == "rules.pdf"
        assert result.tab is source_tab
        assert new_page.is_closed()

    async def test_html_in_new_tab_also_switches(self) -> None:
        """Click opening an HTML page in a new tab switches to that page."""
        old_page = FakePage(url="https://example.com")
        ctx = FakeContext([old_page])
        browser = _make_browser(ctx)

        new_page = FakePage(url="https://example.com/other")
        html_response = _fake_response(
            url=new_page.url,
            content_type="text/html",
            frame=new_page.main_frame,
        )

        async def fake_click() -> None:
            ctx.open_tab(new_page)
            new_page.emit("response", html_response)

        result = await browser.coordinate_action(
            fake_click,
            source_tab=browser.get_tab(1),
            wait_for_navigation=False,
        )

        assert result.tab is browser.get_tab(2)
        assert result.navigation_response is html_response
        assert result.download is None

    async def test_html_in_new_tab_switches_even_with_no_response(self) -> None:
        """A new tab whose document response was never seen is still where the agent is.

        The listener attaches when the tab is created, so a response that lands
        outside that window is missed.  That is the case that used to fall back to
        the page the click started from, leaving the agent staring at an unchanged
        snapshot while the real content sat in a tab it was never told about.
        """
        old_page = FakePage(url="https://example.com")
        ctx = FakeContext([old_page])
        browser = _make_browser(ctx)

        new_page = FakePage(url="https://example.com/other")

        async def fake_click() -> None:
            ctx.open_tab(new_page)  # no response ever emitted

        result = await browser.coordinate_action(
            fake_click,
            source_tab=browser.get_tab(1),
            wait_for_navigation=False,
        )

        assert result.tab is browser.get_tab(2)
        assert result.navigation_response is None
        assert result.download is None

    async def test_no_new_tab_uses_original_page(self) -> None:
        """A click that opens no tab stays on the original page."""
        old_page = FakePage(url="https://example.com")
        ctx = FakeContext([old_page])
        browser = _make_browser(ctx)

        same_page_response = _fake_response(
            url=old_page.url,
            content_type="text/html",
            frame=old_page.main_frame,
        )

        async def fake_click() -> None:
            # Response on the same page (normal navigation)
            old_page.emit("response", same_page_response)

        result = await browser.coordinate_action(
            fake_click,
            source_tab=browser.get_tab(1),
            wait_for_navigation=False,
        )

        assert result.tab is browser.get_tab(1)
        assert result.navigation_response is same_page_response

    async def test_new_tab_about_blank_stays_on_original(self) -> None:
        """A new tab left at about:blank with no response stays on the original page."""
        old_page = FakePage(url="https://example.com")
        ctx = FakeContext([old_page])
        browser = _make_browser(ctx)

        blank_page = FakePage(url="about:blank")

        async def fake_click() -> None:
            ctx.open_tab(blank_page)
            # No response, no download — just an empty tab

        result = await browser.coordinate_action(
            fake_click,
            source_tab=browser.get_tab(1),
            wait_for_navigation=False,
        )

        assert result.tab is browser.get_tab(1)

    async def test_response_listeners_cleaned_up(self) -> None:
        """Response listeners on new pages are removed after the interaction."""
        old_page = FakePage(url="https://example.com")
        ctx = FakeContext([old_page])
        browser = _make_browser(ctx)

        new_page = FakePage(url="https://example.com/file.pdf")
        html_response = _fake_response(
            url=new_page.url,
            content_type="text/html",
            frame=new_page.main_frame,
        )

        async def fake_click() -> None:
            ctx.open_tab(new_page)
            new_page.emit("response", html_response)

        await browser.coordinate_action(
            fake_click,
            source_tab=browser.get_tab(1),
            wait_for_navigation=False,
        )

        assert not new_page._listeners.get("response", [])

    async def test_closed_blank_popup_returns_source_tab(self) -> None:
        old_page = FakePage()
        ctx = FakeContext([old_page])
        browser = _make_browser(ctx)

        async def click():
            popup = FakePage(url="about:blank")
            ctx.open_tab(popup)
            await popup.close()

        result = await browser.coordinate_action(
            click, source_tab=browser.get_tab(1), wait_for_navigation=False,
        )

        assert result.tab is browser.get_tab(1)
        assert result.download is None

    @pytest.mark.parametrize("source_response", [False, True])
    @pytest.mark.parametrize("close_popup", [False, True])
    async def test_popup_download_is_reported_from_source(
        self, tmp_path: Path, source_response: bool, close_popup: bool,
    ) -> None:
        old_page = FakePage()
        ctx = FakeContext([old_page])
        browser = _make_browser(ctx, downloads_dir=str(tmp_path))
        opaque_path = tmp_path / "opaque-report"
        opaque_path.write_bytes(b"report")
        download = AsyncMock()
        download.path.return_value = str(opaque_path)
        download.suggested_filename = "report.csv"

        async def click():
            popup = FakePage(url="about:blank")
            ctx.open_tab(popup)
            popup.emit("download", download)
            if close_popup:
                await popup.close()
            if source_response:
                old_page.emit("response", _fake_response(url=old_page.url, frame=old_page.main_frame))

        source_tab = browser.get_tab(1)
        result = await browser.coordinate_action(
            click, source_tab=source_tab, wait_for_navigation=False,
        )

        assert result.tab is source_tab
        assert result.download is not None
        assert result.download.filename == "report.csv"
        assert Path(result.download.path).read_bytes() == b"report"

    @pytest.mark.parametrize("close_popup", [False, True])
    async def test_source_download_with_popup_is_reported(self, tmp_path: Path, close_popup: bool) -> None:
        old_page = FakePage()
        ctx = FakeContext([old_page])
        browser = _make_browser(ctx, downloads_dir=str(tmp_path))
        opaque_path = tmp_path / "opaque-report"
        opaque_path.write_bytes(b"report")
        download = AsyncMock()
        download.path.return_value = str(opaque_path)
        download.suggested_filename = "report.csv"

        async def click():
            popup = FakePage(url="https://example.com/report")
            ctx.open_tab(popup)
            popup.emit("response", _fake_response(url=popup.url, frame=popup.main_frame))
            old_page.emit("download", download)
            if close_popup:
                await popup.close()

        result = await browser.coordinate_action(
            click, source_tab=browser.get_tab(1), wait_for_navigation=False,
        )

        assert result.tab is browser.get_tab(1)
        assert result.download is not None
        assert result.download.filename == "report.csv"


@pytest.mark.unit
@pytest.mark.asyncio
class TestDownloadFilename:
    """Verify download filenames through the public action boundary."""

    @staticmethod
    async def _download(
        browser: Browser,
        page: FakePage,
        download: AsyncMock,
    ):
        async def action() -> None:
            page.emit("download", download)

        return await browser.coordinate_action(
            action,
            source_tab=browser.get_tab(1),
            wait_for_navigation=False,
        )

    async def test_renames_to_suggested_filename(self, tmp_path: Path) -> None:
        """Download file is renamed from UUID to the server's suggested name."""
        page = FakePage()
        browser = _make_browser(FakeContext([page]), downloads_dir=str(tmp_path))

        # Simulate a Playwright download with a UUID path and suggested name
        uuid_file = tmp_path / "abc123-def456"
        uuid_file.write_bytes(b"%PDF-1.4 fake pdf content")

        download = AsyncMock()
        download.path = AsyncMock(return_value=str(uuid_file))
        download.suggested_filename = "BoardRules_March2026.pdf"

        result = await self._download(browser, page, download)

        assert result.download is not None
        info = result.download
        assert info.filename == "BoardRules_March2026.pdf"
        assert info.content_type == "application/pdf"
        assert info.path == str(tmp_path / "BoardRules_March2026.pdf")
        # Original UUID file should have been moved
        assert not uuid_file.exists()
        assert (tmp_path / "BoardRules_March2026.pdf").exists()

    async def test_deduplicates_suggested_filename(self, tmp_path: Path) -> None:
        """Conflicting filenames get a unique suffix."""
        page = FakePage()
        browser = _make_browser(FakeContext([page]), downloads_dir=str(tmp_path))

        # Pre-existing file with the same name
        (tmp_path / "report.pdf").write_bytes(b"existing")

        uuid_file = tmp_path / "some-uuid"
        uuid_file.write_bytes(b"%PDF-1.4 new content")

        download = AsyncMock()
        download.path = AsyncMock(return_value=str(uuid_file))
        download.suggested_filename = "report.pdf"

        result = await self._download(browser, page, download)

        assert result.download is not None
        info = result.download
        assert info.filename != "report.pdf"
        assert info.filename.startswith("report_")
        assert info.filename.endswith(".pdf")
        assert info.content_type == "application/pdf"

    async def test_falls_back_to_uuid_path(self, tmp_path: Path) -> None:
        """Falls back to the original path when no suggested filename."""
        page = FakePage()
        browser = _make_browser(FakeContext([page]), downloads_dir=str(tmp_path))

        uuid_file = tmp_path / "some-uuid-name"
        uuid_file.write_bytes(b"some content")

        download = AsyncMock()
        download.path = AsyncMock(return_value=str(uuid_file))
        # No suggested_filename attribute
        del download.suggested_filename

        result = await self._download(browser, page, download)

        assert result.download is not None
        info = result.download
        assert info.filename == "some-uuid-name"


@pytest.mark.asyncio
@pytest.mark.parametrize("navigate", [False, True], ids=["click", "goto"])
async def test_parallel_tab_downloads_are_reported_to_their_own_actions(tmp_path: Path, navigate: bool) -> None:
    pages = [FakePage(url=f"https://example.com/report-{i}") for i in range(2)]
    browser = _make_browser(FakeContext(pages), downloads_dir=str(tmp_path))
    both_started = asyncio.Event()
    started = 0

    async def download_report(index: int):
        path = tmp_path / f"opaque-{index}"
        path.write_bytes(f"report {index}".encode())

        async def completed_path():
            nonlocal started
            started += 1
            if started == 2:
                both_started.set()
            await both_started.wait()
            return str(path)

        download = AsyncMock()
        download.path.side_effect = completed_path
        download.suggested_filename = f"report-{index}.csv"

        async def click_download():
            pages[index].emit("download", download)

        if navigate:
            async def goto_download(*args, **kwargs):
                await click_download()
                raise PlaywrightError("net::ERR_ABORTED")

            pages[index].goto = goto_download
            pages[index].wait_for_event = AsyncMock()
            return await browser.navigate(
                f"https://example.com/report-{index}.csv", tab=browser.get_tab(index + 1),
            )

        return await browser.coordinate_action(
            click_download,
            source_tab=browser.get_tab(index + 1),
            wait_for_navigation=False,
        )

    results = await asyncio.wait_for(
        asyncio.gather(download_report(0), download_report(1)), timeout=2,
    )

    for index, result in enumerate(results):
        assert result.download is not None, f"tab {index + 1} lost its download"
        assert result.download.filename == f"report-{index}.csv"
        assert Path(result.download.path).read_bytes() == f"report {index}".encode()


@pytest.mark.asyncio
async def test_other_tab_action_does_not_wait_for_unrelated_download(tmp_path: Path) -> None:
    pages = [FakePage(), FakePage()]
    browser = _make_browser(FakeContext(pages), downloads_dir=str(tmp_path))
    started = asyncio.Event()
    complete = asyncio.Event()
    path = tmp_path / "opaque-report"
    path.write_bytes(b"report")

    async def completed_path():
        started.set()
        await complete.wait()
        return str(path)

    download = AsyncMock()
    download.path.side_effect = completed_path
    download.suggested_filename = "report.csv"

    async def click_download():
        pages[0].emit("download", download)

    downloading = asyncio.create_task(browser.coordinate_action(
        click_download, source_tab=browser.get_tab(1), wait_for_navigation=False,
    ))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        other_result = await asyncio.wait_for(browser.coordinate_action(
            AsyncMock(), source_tab=browser.get_tab(2), wait_for_navigation=False,
        ), timeout=1)
        assert other_result.download is None
        assert not downloading.done()
    finally:
        complete.set()
        download_result = await downloading

    assert download_result.download is not None
    assert download_result.download.filename == "report.csv"
