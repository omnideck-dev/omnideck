"""Downloads and ordinary pages that arrive in a tab the site opened.

A click can open a tab (``target="_blank"``, ``window.open``).  What lands in
it is either a file, which is a download, or an ordinary page, which is simply
where the agent now is.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.unit.tools.browser.support.playwright_stubs import EventEmitterStub
from tools.browser.core._file_detection import DownloadInfo
from tools.browser.core.browser import Browser, BrowserInteractionResult


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

    async def set_viewport_size(self, size: dict[str, int]) -> None:
        return None

    async def wait_for_load_state(self, state: str, timeout: int = 30000) -> None:
        return None


class FakeContext(EventEmitterStub):
    """Stub context with event support."""

    def __init__(self, pages: list[FakePage] | None = None) -> None:
        super().__init__()
        self.pages = pages or []

    async def new_page(self) -> FakePage:
        page = FakePage()
        self.pages.append(page)
        self.emit("page", page)
        return page

    def open_tab(self, page: FakePage) -> None:
        """Simulate a click opening a tab (target=_blank)."""
        self.pages.append(page)
        self.emit("page", page)


def _make_browser(ctx: FakeContext) -> Browser:
    return Browser(context=ctx, extra_headers={})  # type: ignore[arg-type]


def _fake_response(
    content_type: str = "text/html",
    resource_type: str = "document",
) -> MagicMock:
    resp = MagicMock()
    resp.headers = {"content-type": content_type}
    resp.request.resource_type = resource_type
    return resp


# ---------------------------------------------------------------------------
# _track_page — download listener auto-attachment
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestContextPageHandler:
    """Verify that tabs the site opens get download listeners immediately."""

    def test_new_tab_gets_download_listener(self) -> None:
        """A tab opened by a click should have a download listener attached."""
        ctx = FakeContext([FakePage()])
        browser = _make_browser(ctx)

        new_page = FakePage(url="https://example.com/file.pdf")
        ctx.open_tab(new_page)

        # The download listener registers the page id in the tracking set
        assert id(new_page) in browser._download_listener_pages

    def test_existing_pages_not_auto_attached(self) -> None:
        """Pages that existed before Browser init don't get auto-attached."""
        existing = FakePage()
        ctx = FakeContext([existing])
        browser = _make_browser(ctx)

        # Existing page is NOT auto-attached (it gets attached lazily by
        # current_page() on first use)
        assert id(existing) not in browser._download_listener_pages


# ---------------------------------------------------------------------------
# perform_interaction — new tab detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestPerformInteractionNewTab:
    """Verify that perform_interaction detects files opened in new tabs."""

    async def test_pdf_in_new_tab_detected_via_response(self) -> None:
        """Click opening a PDF in a new tab captures the new page's response."""
        old_page = FakePage(url="https://texas.gov/rules")
        ctx = FakeContext([old_page])
        browser = _make_browser(ctx)

        pdf_response = _fake_response(content_type="application/pdf")
        new_page = FakePage(url="https://texas.gov/rules.pdf")

        # The action simulates a click that opens a new tab.
        # The new page fires a document response with application/pdf.
        async def fake_click() -> None:
            ctx.open_tab(new_page)
            # Simulate the new page firing a response event
            new_page.emit("response", pdf_response)

        finalize_args: dict[str, Any] = {}
        original_finalize = browser._finalize_action

        async def capture_finalize(page: Any, **kwargs: Any) -> BrowserInteractionResult:
            finalize_args["page"] = page
            finalize_args["response"] = kwargs.get("response")
            return BrowserInteractionResult()

        with (
            patch.object(browser, "_finalize_action", side_effect=capture_finalize),
        ):
            await browser.perform_interaction(fake_click, source_page=old_page)

        assert finalize_args["page"] is new_page
        assert finalize_args["response"] is pdf_response

    async def test_download_event_in_new_tab_detected(self) -> None:
        """Click opening a PDF in a new tab is detected via download event."""
        old_page = FakePage(url="https://texas.gov/rules")
        ctx = FakeContext([old_page])
        browser = _make_browser(ctx)

        new_page = FakePage(url="about:blank")

        download_info = DownloadInfo(
            path="/home/computron/rules.pdf",
            content_type="application/pdf",
            size_bytes=50000,
            filename="rules.pdf",
        )

        async def fake_click() -> None:
            ctx.open_tab(new_page)
            # Simulate a download being captured (as --disable-pdf-viewer does)
            browser._pending_downloads.append(download_info)

        finalize_args: dict[str, Any] = {}

        async def capture_finalize(page: Any, **kwargs: Any) -> BrowserInteractionResult:
            finalize_args["page"] = page
            finalize_args["response"] = kwargs.get("response")
            return BrowserInteractionResult()

        with (
            patch.object(browser, "_finalize_action", side_effect=capture_finalize),
        ):
            await browser.perform_interaction(fake_click, source_page=old_page)

        # Should switch to the new page since a download was detected
        assert finalize_args["page"] is new_page

    async def test_html_in_new_tab_also_switches(self) -> None:
        """Click opening an HTML page in a new tab switches to that page."""
        old_page = FakePage(url="https://example.com")
        ctx = FakeContext([old_page])
        browser = _make_browser(ctx)

        html_response = _fake_response(content_type="text/html")
        new_page = FakePage(url="https://example.com/other")

        async def fake_click() -> None:
            ctx.open_tab(new_page)
            new_page.emit("response", html_response)

        finalize_args: dict[str, Any] = {}

        async def capture_finalize(page: Any, **kwargs: Any) -> BrowserInteractionResult:
            finalize_args["page"] = page
            finalize_args["response"] = kwargs.get("response")
            return BrowserInteractionResult()

        with (
            patch.object(browser, "_finalize_action", side_effect=capture_finalize),
        ):
            await browser.perform_interaction(fake_click, source_page=old_page)

        # New tab with an HTML response should also be detected
        assert finalize_args["page"] is new_page
        assert finalize_args["response"] is html_response

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

        finalize_args: dict[str, Any] = {}

        async def capture_finalize(page: Any, **kwargs: Any) -> BrowserInteractionResult:
            finalize_args["page"] = page
            return BrowserInteractionResult()

        probe = AsyncMock(return_value=None)
        with (
            patch.object(browser, "_finalize_action", side_effect=capture_finalize),
            patch.object(browser, "_probe_file_url", probe),
        ):
            await browser.perform_interaction(fake_click, source_page=old_page)

        # Probed for a file, found none, and stayed on the new tab regardless.
        probe.assert_awaited_once()
        assert finalize_args["page"] is new_page

    async def test_download_in_new_tab_returns_the_agent_to_the_source(self) -> None:
        """A file downloaded in a new tab closes it and hands the agent back."""
        old_page = FakePage(url="https://example.com")
        ctx = FakeContext([old_page])
        browser = _make_browser(ctx)

        new_page = FakePage(url="https://example.com/report.pdf")
        pdf_response = _fake_response(content_type="application/pdf")

        async def fake_click() -> None:
            ctx.open_tab(new_page)
            new_page.emit("response", pdf_response)

        async def capture_finalize(page: Any, **kwargs: Any) -> BrowserInteractionResult:
            result = BrowserInteractionResult(
                download=DownloadInfo(
                    path="/tmp/report.pdf",
                    content_type="application/pdf",
                    size_bytes=1024,
                    filename="report.pdf",
                ),
            )
            # What the real _finalize_action records: the tab it settled on.
            result.settled_page = page
            return result

        with patch.object(browser, "_finalize_action", side_effect=capture_finalize):
            result = await browser.perform_interaction(fake_click, source_page=old_page)

        # The new tab was the settled tab, but a download closes it.  The result has
        # to name the tab the agent is actually on now, or the snapshot and the
        # screenshot would both chase a dead tab.
        assert new_page.is_closed()
        assert result.settled_page is old_page

    async def test_no_new_tab_uses_original_page(self) -> None:
        """A click that opens no tab stays on the original page."""
        old_page = FakePage(url="https://example.com")
        ctx = FakeContext([old_page])
        browser = _make_browser(ctx)

        same_page_response = _fake_response(content_type="text/html")
        # Attach main_frame so the response listener matches
        same_page_response.frame = old_page.main_frame

        async def fake_click() -> None:
            # Response on the same page (normal navigation)
            old_page.emit("response", same_page_response)

        finalize_args: dict[str, Any] = {}

        async def capture_finalize(page: Any, **kwargs: Any) -> BrowserInteractionResult:
            finalize_args["page"] = page
            finalize_args["response"] = kwargs.get("response")
            return BrowserInteractionResult()

        with (
            patch.object(browser, "_finalize_action", side_effect=capture_finalize),
        ):
            await browser.perform_interaction(fake_click, source_page=old_page)

        assert finalize_args["page"] is old_page
        assert finalize_args["response"] is same_page_response

    async def test_new_tab_about_blank_stays_on_original(self) -> None:
        """A new tab left at about:blank with no response stays on the original page."""
        old_page = FakePage(url="https://example.com")
        ctx = FakeContext([old_page])
        browser = _make_browser(ctx)

        blank_page = FakePage(url="about:blank")

        async def fake_click() -> None:
            ctx.open_tab(blank_page)
            # No response, no download — just an empty tab

        finalize_args: dict[str, Any] = {}

        async def capture_finalize(page: Any, **kwargs: Any) -> BrowserInteractionResult:
            finalize_args["page"] = page
            return BrowserInteractionResult()

        with (
            patch.object(browser, "_finalize_action", side_effect=capture_finalize),
        ):
            await browser.perform_interaction(fake_click, source_page=old_page)

        # No response or download on a blank tab → stay on the original page
        assert finalize_args["page"] is old_page

    async def test_response_listeners_cleaned_up(self) -> None:
        """Response listeners on new pages are removed after the interaction."""
        old_page = FakePage(url="https://example.com")
        ctx = FakeContext([old_page])
        browser = _make_browser(ctx)

        new_page = FakePage(url="https://example.com/file.pdf")
        pdf_response = _fake_response(content_type="application/pdf")

        async def fake_click() -> None:
            ctx.open_tab(new_page)
            new_page.emit("response", pdf_response)

        with (
            patch.object(browser, "_finalize_action", return_value=BrowserInteractionResult()),
        ):
            await browser.perform_interaction(fake_click, source_page=old_page)

        # The response listener should have been removed from the new page
        assert not new_page._listeners.get("response", [])


# ---------------------------------------------------------------------------
# _handle_download — suggested filename rename
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestHandleDownloadRename:
    """Verify that _handle_download renames files to the suggested filename."""

    async def test_renames_to_suggested_filename(self, tmp_path: Path) -> None:
        """Download file is renamed from UUID to the server's suggested name."""
        ctx = FakeContext([FakePage()])
        browser = _make_browser(ctx)
        browser._downloads_dir = str(tmp_path)

        # Simulate a Playwright download with a UUID path and suggested name
        uuid_file = tmp_path / "abc123-def456"
        uuid_file.write_bytes(b"%PDF-1.4 fake pdf content")

        download = AsyncMock()
        download.path = AsyncMock(return_value=str(uuid_file))
        download.suggested_filename = "BoardRules_March2026.pdf"

        await browser._handle_download(download)

        assert len(browser._pending_downloads) == 1
        info = browser._pending_downloads[0]
        assert info.filename == "BoardRules_March2026.pdf"
        assert info.content_type == "application/pdf"
        assert info.path == str(tmp_path / "BoardRules_March2026.pdf")
        # Original UUID file should have been moved
        assert not uuid_file.exists()
        assert (tmp_path / "BoardRules_March2026.pdf").exists()

    async def test_deduplicates_suggested_filename(self, tmp_path: Path) -> None:
        """Conflicting filenames get a unique suffix."""
        ctx = FakeContext([FakePage()])
        browser = _make_browser(ctx)
        browser._downloads_dir = str(tmp_path)

        # Pre-existing file with the same name
        (tmp_path / "report.pdf").write_bytes(b"existing")

        uuid_file = tmp_path / "some-uuid"
        uuid_file.write_bytes(b"%PDF-1.4 new content")

        download = AsyncMock()
        download.path = AsyncMock(return_value=str(uuid_file))
        download.suggested_filename = "report.pdf"

        await browser._handle_download(download)

        info = browser._pending_downloads[0]
        assert info.filename != "report.pdf"
        assert info.filename.startswith("report_")
        assert info.filename.endswith(".pdf")
        assert info.content_type == "application/pdf"

    async def test_falls_back_to_uuid_path(self, tmp_path: Path) -> None:
        """Falls back to the original path when no suggested filename."""
        ctx = FakeContext([FakePage()])
        browser = _make_browser(ctx)
        browser._downloads_dir = str(tmp_path)

        uuid_file = tmp_path / "some-uuid-name"
        uuid_file.write_bytes(b"some content")

        download = AsyncMock()
        download.path = AsyncMock(return_value=str(uuid_file))
        # No suggested_filename attribute
        del download.suggested_filename

        await browser._handle_download(download)

        info = browser._pending_downloads[0]
        assert info.filename == "some-uuid-name"
