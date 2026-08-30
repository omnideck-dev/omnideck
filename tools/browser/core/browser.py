"""Core Playwright browser utilities for agent tools."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from playwright.async_api import (
    BrowserContext,
    Frame,
    Page,
    Playwright,
    Response,
)
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from config import load_config
from tools.browser.core.challenges import detect_challenge
from tools.browser.core.downloads import DownloadInfo
from tools.browser.core.exceptions import BrowserToolError
from tools.browser.core.tab import Tab

if TYPE_CHECKING:  # Imported only for type checking to avoid runtime dependency surface
    from playwright.async_api import Geolocation, ProxySettings
    from tools.browser.core.host import BrowserHost

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ActionResult:
    """Complete outcome of one browser-coordinated action."""

    # A successful action always has a resulting tab. Requiring it here keeps
    # callers from carrying a separate source-tab fallback through formatting.
    tab: Tab
    navigation_response: Response | None = None
    download: DownloadInfo | None = None
    document_transition: str | None = None
    action_ms: float = 0.0
    navigation_wait_ms: float = 0.0


class Browser:
    """Minimal Playwright browser core for powering LLM tools.

    Example:
        browser = await Browser.start(storage_state=saved_state)
        tab = await browser.new_tab()
        await browser.navigate("https://example.com", tab=tab)
        ...
        await browser.close()
    """

    def __init__(
        self,
        context: BrowserContext,
        extra_headers: dict[str, str] | None = None,
        pw: Playwright | None = None,
        downloads_dir: str = "",
    ) -> None:
        """Initialize the browser wrapper.

        Args:
            context: The Playwright browser context.
            extra_headers: Default HTTP headers applied to all requests.
            pw: The Playwright driver instance used to launch the browser.
            downloads_dir: Directory where captured downloads are stored.
        """
        self._context: BrowserContext = context
        self._extra_headers: dict[str, str] = extra_headers or {}
        self._pw: Playwright | None = pw
        self._owned_host: BrowserHost | None = None
        self._closed: bool = False
        self._tabs_by_id: dict[int, Tab] = {}
        self._tabs_by_page: dict[Page, Tab] = {}
        self._next_tab_id: int = 0
        self._pending_downloads: list[DownloadInfo] = []
        self._downloads_dir = downloads_dir
        self._download_listener_pages: set[int] = set()  # page id() tracking
        self._download_tasks: set[asyncio.Task[None]] = set()
        self._download_event: asyncio.Event = asyncio.Event()

        # Track every page the context creates (opened by us, by a link, or
        # target=_blank) the moment it exists: stable tab id + download + close.
        self._context.on("page", self._track_page)
        for page in self._context.pages:
            self._track_page(page)

    def _attach_download_listener(self, page: Page) -> None:
        """Attach a download event listener to a page if not already attached."""
        page_id = id(page)
        if page_id in self._download_listener_pages:
            return
        self._download_listener_pages.add(page_id)

        def _on_download(download: Any) -> None:
            task = asyncio.ensure_future(self._handle_download(download))
            self._download_tasks.add(task)
            task.add_done_callback(self._download_tasks.discard)

        page.on("download", _on_download)

    def _track_page(self, page: Page) -> None:
        """Assign a stable tab ID and attach download + close handlers.

        Registered as the context ``page`` listener, so it fires for every page
        — opened by us, or by the site itself via ``target=_blank`` or
        ``window.open`` — the moment it's created, before any other ``page``
        listener runs. That means a tab the site opens gets a stable ID and is
        visible to anything mirroring the tab set, not only
        tabs opened via ``new_tab``. Guards against double-tracking the same
        page (re-entry is a no-op).
        """
        if page in self._tabs_by_page:
            self._attach_download_listener(page)
            return
        self._next_tab_id += 1
        tab = Tab(self._next_tab_id, page)
        self._tabs_by_id[tab.id] = tab
        self._tabs_by_page[page] = tab
        self._attach_download_listener(page)

        def _on_frame_navigated(frame: Frame) -> None:
            tab._handle_frame_navigated(frame)

        def _on_close(_p: Any) -> None:
            self._tabs_by_page.pop(page, None)
            self._tabs_by_id.pop(tab.id, None)
            tab._invalidate_document()

        page.on("framenavigated", _on_frame_navigated)
        page.on("close", _on_close)

    async def _handle_download(self, download: Any) -> None:
        """Process a Playwright download event and record the result."""
        try:
            path = await download.path()
            if not path:
                logger.warning("Download completed but no path available")
                return

            # Playwright saves downloads with opaque UUID filenames.  Rename
            # to the server's suggested name so the agent sees a meaningful
            # filename and MIME-type detection works correctly.
            suggested: str = getattr(download, "suggested_filename", "")
            if suggested and self._downloads_dir:
                dest = Path(self._downloads_dir) / suggested
                if dest.exists():
                    stem, suffix = dest.stem, dest.suffix
                    suggested = f"{stem}_{secrets.token_hex(4)}{suffix}"
                    dest = Path(self._downloads_dir) / suggested
                try:
                    Path(path).rename(dest)
                    path = str(dest)
                except OSError:
                    logger.debug("Could not rename download to %s", suggested)

            from tools.browser.core.downloads import build_download_info_from_path

            info = build_download_info_from_path(path)
            self._pending_downloads.append(info)
            self._download_event.set()
            logger.info(
                "Download captured: %s (%s, %d bytes)",
                info.filename,
                info.content_type,
                info.size_bytes,
            )
        except Exception:
            logger.exception("Failed to process download event")

    def _drain_downloads(self) -> list[DownloadInfo]:
        """Return and clear any pending downloads captured since the last drain."""
        downloads = list(self._pending_downloads)
        self._pending_downloads.clear()
        return downloads

    @classmethod
    async def start(
        cls,
        *,
        storage_state: dict[str, Any] | str | None = None,
        headless: bool = False,
        locale: str = "en-US",
        timezone_id: str = "America/Chicago",
        proxy: ProxySettings | None = None,
        accept_downloads: bool = True,
        downloads_path: str | None = None,
        geolocation: Geolocation | None = None,
        permissions: list[str] | None = None,
        extra_headers: dict[str, str] | None = None,
        args: list[str] | None = None,
    ) -> Browser:
        """Launch system Chrome and create one independently owned session.

        A caller may seed the context with a Playwright storage-state document.
        Closing a Browser never persists its state; persistence is an explicit
        application-level operation.

        Args:
            storage_state: Playwright storage state to seed the new context.
            headless: Whether to launch without a visible window.
            locale: BCP 47 locale tag.
            timezone_id: IANA timezone ID to emulate.
            proxy: Optional proxy settings for the browser.
            accept_downloads: Whether to allow automatic downloads.
            downloads_path: Directory where downloaded files are saved.
            geolocation: Optional geolocation to emulate.
            permissions: Optional list of permissions to grant to all pages.
            extra_headers: Additional default HTTP headers for all requests.
            args: Additional Chromium command-line flags.

        Returns:
            A ready-to-use ``Browser`` wrapping the context.
        """
        from tools.browser.core.host import BrowserHost

        host = await BrowserHost.start(
            headless=headless,
            locale=locale,
            timezone_id=timezone_id,
            proxy=proxy,
            accept_downloads=accept_downloads,
            downloads_path=downloads_path,
            geolocation=geolocation,
            permissions=permissions,
            extra_headers=extra_headers,
            args=args,
        )
        try:
            instance = await host.create_session(storage_state=storage_state)
        except Exception:
            await host.close()
            raise
        instance._owned_host = host
        return instance

    async def close_session(self) -> None:
        """Close only this session's context, leaving its shared host running.

        Used for ephemeral sub-agent contexts that share the root's Chromium
        process.  The ``close()`` method is inappropriate here because it also
        stops the Playwright driver, which would kill the shared process.
        """
        if self._closed:
            return
        self._closed = True
        for page in list(self._context.pages):
            try:
                if not page.is_closed():
                    await asyncio.wait_for(page.close(), timeout=3.0)
            except Exception:  # noqa: BLE001
                pass
        try:
            await asyncio.wait_for(self._context.close(), timeout=5.0)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to close ephemeral browser context")

    async def capture_storage_state(self) -> dict[str, Any]:
        """Capture transferable cookies, local storage, and IndexedDB."""
        return await self._context.storage_state(indexed_db=True)

    async def new_tab(self) -> Tab:
        """Open and return a new stable tab.

        Assigns a stable monotonic tab ID that never repeats — closing a
        tab does not free its ID for reuse, so a later call that uses
        the old ID errors instead of pointing at a different page.

        Returns:
            The newly created ``Tab``.

        Raises:
            BrowserToolError: If the open-tab limit is already reached.
        """
        limit = load_config().tools.browser.max_open_tabs
        open_count = len(self.tabs())
        if open_count >= limit:
            raise BrowserToolError(
                f"Tab limit reached ({open_count}/{limit} open). Close a tab with "
                f"close_tab(tab=N) before opening another, or reuse an existing tab "
                f"with goto(url, tab=N).\n{self._tab_listing()}",
                tool="new_tab",
            )
        # The context "page" event (handled by _track_page) assigns the tab id
        # and attaches the download + close handlers as the page is created.
        # Viewport is inherited from the context's default (set once at creation)
        # so every tab — opened by us or by the site — is the same size, like
        # tabs in a real browser window; don't re-roll a per-tab viewport here.
        page = await self._context.new_page()
        return self._require_tab_for_page(page)

    def subscribe_to_new_tabs(
        self,
        callback: Callable[[Tab], None],
    ) -> Callable[[], None]:
        """Subscribe to newly opened tabs and return an unsubscribe callback."""

        def _on_page(page: Page) -> None:
            tab = self._tabs_by_page.get(page)
            if tab is not None:
                callback(tab)

        self._context.on("page", _on_page)

        def _unsubscribe() -> None:
            self._context.remove_listener("page", _on_page)

        return _unsubscribe

    def tabs(self) -> list[Tab]:
        """Return open tabs in browser order."""
        return [
            self._tabs_by_page[page]
            for page in self._context.pages
            if page in self._tabs_by_page and not page.is_closed()
        ]

    def get_tab(self, tab: str | int) -> Tab:
        """Return the open tab with the given stable ID."""
        try:
            target_id = int(str(tab).strip())
        except ValueError:
            raise ValueError(
                f"tab={tab!r} is not a valid ID. {self._tab_listing()}",
            ) from None
        resolved = self._tabs_by_id.get(target_id)
        if resolved is not None and not resolved.is_closed():
            return resolved
        raise ValueError(
            f"tab={tab!r} not found. {self._tab_listing()}",
        )

    def _tab_for_page(self, page: Page) -> Tab | None:
        """Return the tab owning a Playwright page, if it is tracked."""
        return self._tabs_by_page.get(page)

    def _tab_listing(self) -> str:
        """Render the open-tabs listing used in error messages."""
        rows = []
        for tab in self.tabs():
            rows.append(f"  tab={tab.id}: {tab.url}")
        return "Open tabs:\n" + "\n".join(rows) if rows else "No open tabs"

    def _require_tab_for_page(self, page: Page) -> Tab:
        tab = self._tabs_by_page.get(page)
        if tab is None:
            raise ValueError("Playwright page is not tracked as a browser tab")
        return tab

    async def navigate(
        self,
        url: str,
        *,
        tab: Tab,
    ) -> ActionResult:
        """Navigate *tab* to *url* and return a ``ActionResult``.

        Raises ``BrowserToolError`` if *tab* is already navigating —
        concurrent goto on the same tab is the loud-error case that
        teaches the agent to use ``new_tab`` for parallelism.
        """
        page = tab._page_for_browser()
        if self._tabs_by_id.get(tab.id) is not tab or tab.is_closed():
            raise BrowserToolError("Browser tab is no longer open", tool="goto")
        if tab._navigation_in_progress():
            raise BrowserToolError(
                f"Navigation already in flight on tab={tab.id}. Use new_tab(url) to open in parallel.",
                tool="goto",
            )
        tab._begin_navigation()
        # Any cached dominant iframe belongs to the old DOM; drop it
        # so the post-nav settle re-detects against the new one.
        tab._invalidate_document()
        self._pending_downloads.clear()
        initial_url = getattr(page, "url", "")
        try:
            try:
                response = await page.goto(url, wait_until="domcontentloaded")
            except PlaywrightError as exc:
                # When --disable-pdf-viewer converts a navigation to a download,
                # Chromium aborts the page load with net::ERR_ABORTED.  The
                # download listener captures the file asynchronously — wait
                # for the download event before falling through to finalize.
                if "net::ERR_ABORTED" not in str(exc):
                    raise
                logger.debug("Navigation aborted (likely download): %s", url)
                response = None
                try:
                    await page.wait_for_event("download", timeout=5_000)
                except (PlaywrightTimeoutError, PlaywrightError):
                    pass
            return await self._finalize_action(
                page,
                response=response,
                initial_url=initial_url,
            )
        finally:
            tab._finish_navigation()

    async def navigate_back(
        self,
        tab: Tab,
    ) -> ActionResult:
        """Navigate *tab* back in history via ``coordinate_action``."""
        page = tab._page_for_browser()

        async def _back() -> None:
            try:
                await asyncio.wait_for(
                    page.go_back(wait_until="domcontentloaded"),
                    timeout=10.0,
                )
            except (asyncio.TimeoutError, PlaywrightError):
                # SPA may handle back navigation client-side without firing
                # domcontentloaded. Fall through to document settling/rendering.
                logger.debug("go_back timed out (SPA likely handled navigation client-side)")

        return await self.coordinate_action(_back, source_tab=tab)

    # Timeouts for individual shutdown steps.  These are generous enough for
    # well-behaved pages but prevent indefinite hangs when Chromium is stuck.
    _PAGE_CLOSE_TIMEOUT_S: float = 3.0
    _CONTEXT_CLOSE_TIMEOUT_S: float = 5.0
    _PW_STOP_TIMEOUT_S: float = 5.0

    async def close(self) -> None:
        """Close the browser context and stop the Playwright driver.

        Each shutdown step (page close, context close, driver stop) is guarded
        by a timeout so that a hung Chromium process cannot block the caller
        indefinitely.  Stopping the Playwright driver (the last step) kills its
        subprocess which also terminates the browser, so even if the earlier
        steps time out the browser is cleaned up.

        The method is idempotent and safe to call multiple times.
        """
        if self._closed:
            logger.debug("Browser.close called but already closed")
            return
        self._closed = True

        context_exc: Exception | None = None
        pages_to_close = list(self._context.pages)
        for page in pages_to_close:
            try:
                if getattr(page, "is_closed", lambda: False)():
                    continue
            except Exception:  # noqa: BLE001 - treat unknown failures as closed
                continue
            try:
                logger.debug("Closing page %s before shutdown", getattr(page, "url", "<unknown>"))
                await asyncio.wait_for(page.close(), timeout=self._PAGE_CLOSE_TIMEOUT_S)
            except asyncio.TimeoutError:
                logger.warning("Timed out closing page %s — proceeding", getattr(page, "url", "<unknown>"))
            except PlaywrightError as exc:  # pragma: no cover - defensive
                logger.debug("Suppressed exception while closing page: %s: %s", type(exc).__name__, exc)
            except Exception as exc:  # noqa: BLE001  pragma: no cover - highly defensive
                logger.debug("Unexpected exception while closing page: %s: %s", type(exc).__name__, exc)
        try:
            logger.debug("Closing Playwright BrowserContext ...")
            await asyncio.wait_for(self._context.close(), timeout=self._CONTEXT_CLOSE_TIMEOUT_S)
            logger.debug("BrowserContext closed")
        except asyncio.TimeoutError:
            context_exc = asyncio.TimeoutError("BrowserContext.close() timed out")
            logger.warning(
                "Timed out closing BrowserContext after %.1fs — will force-stop driver",
                self._CONTEXT_CLOSE_TIMEOUT_S,
            )
        except PlaywrightError as exc:  # pragma: no cover - relies on Playwright internals
            context_exc = exc
            logger.warning(
                "Suppressed exception while closing BrowserContext: %s: %s",
                type(exc).__name__,
                exc,
            )
        except Exception as exc:  # noqa: BLE001  pragma: no cover - highly defensive
            context_exc = exc
            logger.warning(
                "Suppressed unexpected exception while closing BrowserContext: %s: %s",
                type(exc).__name__,
                exc,
            )
        finally:
            if self._owned_host is not None:
                await self._owned_host.close()
            try:
                if self._pw is not None:
                    logger.debug("Stopping Playwright driver ...")
                    await asyncio.wait_for(self._pw.stop(), timeout=self._PW_STOP_TIMEOUT_S)
                    logger.debug("Playwright driver stopped")
            except asyncio.TimeoutError:
                logger.warning(
                    "Timed out stopping Playwright driver after %.1fs",
                    self._PW_STOP_TIMEOUT_S,
                )
            except PlaywrightError as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Suppressed exception while stopping Playwright driver: %s: %s",
                    type(exc).__name__,
                    exc,
                )
            except Exception as exc:  # noqa: BLE001  pragma: no cover - highly defensive
                logger.warning(
                    "Suppressed unexpected exception while stopping Playwright driver: %s: %s",
                    type(exc).__name__,
                    exc,
                )

        if context_exc:
            logger.debug("Browser.close completed with suppressed context exception")

    async def _finalize_action(
        self,
        page: Page,
        *,
        response: Response | None,
        initial_url: str,
        saw_download_response: bool = False,
    ) -> ActionResult:
        """Resolve a tab's new state after a navigation or interaction.

        This is the shared pipeline run after anything changes the page. It
        decides what happened (a download, a challenge, a new document, or an
        in-page frame change), updates the per-tab caches accordingly, and
        returns the result both the navigate and interaction paths hand back.

        *initial_url* is the tab's url before the action; comparing it to the
        settled url tells whether the action navigated. *response* is the
        navigation response when there was one, else None. *saw_download_response*
        flags that a ``Content-Disposition: attachment`` header was seen, so a
        download event may still be in flight.

        Four phases:

        1. Downloads. Drain any captured download; if there is none but the
           response is a file content-type, save the body as a file.

        2. Late downloads. Re-check events that arrived after the action and
           honour a brief grace wait when an attachment header was seen but its
           download event has not fired yet.

        3. Document resolution — the part that updates tab-local state. Exactly
           one case
           applies:
           - download: clear the selected document; the page may be a file-viewer stub
             with no real DOM to resolve.
           - challenge: an anti-bot interstitial is up. Cache it, drop any
             embedded document (tools never act inside the interstitial), and label
             the transition the first time it appears. The response is passed to
             detection so header-only variants are caught here, where the header
             still exists.
           - navigated with no challenge: a fresh document. Clear the selection
             and let the next read resolve it — embedded-document detection
             deliberately skips fresh navigations.
           - otherwise (an in-page change, no navigation): re-run embedded-document
             selection and label a transition when the chosen document changes.

        4. Return the result: the response, any download, and the document
           transition — a short label for the log panel, e.g.
           ``"→ iframe <url>"`` or ``"→ cloudflare challenge"``.
        """
        # 1. Download detection
        download_info: DownloadInfo | None = None

        if self._download_tasks:
            await asyncio.gather(*self._download_tasks, return_exceptions=True)

        pending = self._drain_downloads()
        if pending:
            download_info = pending[0]

        if download_info is None and response is not None:
            from tools.browser.core.downloads import (
                is_file_content_type,
                save_response_as_file,
            )

            ct = response.headers.get("content-type", "")
            if is_file_content_type(ct):
                try:
                    download_info = await save_response_as_file(
                        response,
                        downloads_dir=self._downloads_dir or ".",
                    )
                except Exception:
                    logger.exception("Failed to save file from response")

        # 2. Re-check for downloads that arrived after the action. Page
        # stabilization happens at the render-return boundary, after the selected
        # document has been resolved and immediately before its DOM walk.
        if download_info is None:
            if self._download_tasks:
                await asyncio.gather(*self._download_tasks, return_exceptions=True)
            late_downloads = self._drain_downloads()
            if late_downloads:
                download_info = late_downloads[0]

        # 2b. If we saw a Content-Disposition: attachment response but the
        # Playwright download event hasn't fired yet, wait for it.  This
        # only triggers when an attachment header was observed — zero cost
        # on normal interactions.
        if download_info is None and saw_download_response:
            try:
                await asyncio.wait_for(self._download_event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                logger.debug("Download grace period expired despite attachment header")
            if self._download_tasks:
                await asyncio.gather(*self._download_tasks, return_exceptions=True)
            grace_downloads = self._drain_downloads()
            if grace_downloads:
                download_info = grace_downloads[0]
                logger.info(
                    "Late download captured after attachment response: %s",
                    download_info.filename,
                )

        # 3. Iframe / challenge detection (skip if download — page may be a
        # PDF viewer stub). Operates on this tab's document selection only;
        # other tabs' selected documents are untouched.
        document_transition: str | None = None
        final_url = getattr(page, "url", initial_url)
        navigated = bool(initial_url and final_url and final_url != initial_url)
        tab = self._require_tab_for_page(page)

        if download_info is not None:
            tab._invalidate_document()
        else:
            # Detect before the dominant-iframe path so a challenge wins; the
            # response lets header-only variants be caught here.
            challenge = await detect_challenge(page, response)
            if challenge is not None:
                # Don't enter the interstitial's frame; the banner replaces the
                # rendered document and routes the agent to fetch_url.
                was_challenge = tab.challenge is not None
                tab._set_challenge(challenge)
                if not was_challenge:
                    document_transition = f"→ {challenge.vendor} challenge"
            elif navigated:
                tab._invalidate_document()
            else:
                try:
                    previous_frame, selected = await tab._refresh_content_frame()
                    if selected != previous_frame:
                        if selected is not None:
                            document_transition = f"→ iframe {selected.url}"
                        elif previous_frame is not None:
                            document_transition = "→ main page"
                except Exception:  # noqa: BLE001
                    logger.debug("Embedded document selection failed; keeping current state")

        return ActionResult(
            tab=tab,
            navigation_response=response,
            download=download_info,
            document_transition=document_transition,
        )

    async def _probe_file_url(self, url: str) -> None:
        """Record *url* as a pending download when it turns out to be a file.

        Chrome's PDF viewer extension (non-headless) can silently handle file
        URLs without firing Playwright response or download events.  This
        method fetches the URL directly via the API request context, saves
        the file if it's a non-HTML content-type, and appends a
        ``DownloadInfo`` to ``_pending_downloads``.

        The pending-download list is the whole signal; there is nothing to
        return.  Whether or not the URL was a file, the tab holding it is where
        the agent now is.
        """
        from tools.browser.core.downloads import (
            is_file_content_type,
            save_response_as_file,
        )

        try:
            api_resp = await asyncio.wait_for(
                self._context.request.get(url),
                timeout=15.0,
            )
            ct = api_resp.headers.get("content-type", "")
            if is_file_content_type(ct):
                info = await save_response_as_file(
                    api_resp,
                    downloads_dir=self._downloads_dir or ".",
                )
                self._pending_downloads.append(info)
                logger.info(
                    "Probed file URL in new tab: %s (%s, %d bytes)",
                    info.filename,
                    info.content_type,
                    info.size_bytes,
                )
                await api_resp.dispose()
                return
            await api_resp.dispose()
        except Exception:  # noqa: BLE001
            logger.debug("Failed to probe new tab URL: %s", url)

    async def coordinate_action(
        self,
        action: Callable[[], Awaitable[Any]],
        *,
        source_tab: Tab,
        wait_for_navigation: bool = True,
    ) -> ActionResult:
        """Coordinate a document action with browser-context outcomes.

        When *wait_for_navigation* is True (the default), briefly wait for a
        navigation the action may start a beat late — some sites dispatch a
        click's navigation request only after the click returns (e.g. via a JS
        click handler) — so the post-action rendering reflects the new page
        rather than the old one. Pass False for actions that never navigate
        (scroll, drag, fill) to skip the wait.
        """
        source_page = source_tab._page_for_browser()
        initial_url = source_tab.url

        self._pending_downloads.clear()
        self._download_event.clear()
        captured_responses: list[Response] = []

        # Track tabs the interaction opens (target=_blank, window.open) and
        # capture their document responses, so file downloads in new tabs
        # are detected properly.
        new_pages: list[Page] = []
        responses_by_new_page: dict[Page, list[Response]] = {}
        _np_listeners: list[tuple[Page, Callable[..., Any]]] = []

        _saw_download_response = False

        def _on_response(resp: Response) -> None:
            nonlocal _saw_download_response
            if resp.frame == source_page.main_frame and resp.request.resource_type == "document":
                captured_responses.append(resp)
            # Detect responses that will trigger a download event.  The
            # browser converts these to downloads asynchronously, so the
            # Playwright download event fires after a short delay.
            disposition = resp.headers.get("content-disposition", "")
            if "attachment" in disposition:
                _saw_download_response = True

        def _on_new_page(new_page: Page) -> None:
            new_pages.append(new_page)
            responses = responses_by_new_page.setdefault(new_page, [])

            def _on_np_response(resp: Response) -> None:
                if resp.request.resource_type == "document":
                    responses.append(resp)

            new_page.on("response", _on_np_response)
            _np_listeners.append((new_page, _on_np_response))

        nav_started = asyncio.Event()

        def _on_request(req: Any) -> None:
            # A main-frame navigation request means the action started a
            # navigation — even if it dispatched a beat after the action
            # returned (some sites defer navigation in a JS click handler).
            try:
                if req.is_navigation_request() and req.frame == source_page.main_frame:
                    nav_started.set()
            except Exception:  # noqa: BLE001
                pass

        source_page.on("response", _on_response)
        source_page.on("request", _on_request)
        self._context.on("page", _on_new_page)

        t0 = time.monotonic()
        await action()
        action_ms = (time.monotonic() - t0) * 1000
        navigation_wait_ms = 0.0

        # Bridge the gap between the action returning and a navigation starting.
        # A readiness wait on the old page would return immediately if no
        # navigation has begun yet, producing stale output. Wait briefly
        # for navigation to start, then for it to commit, so rendering resolves
        # the new document. Only nav-capable actions that do not navigate pay
        # the grace period.
        if wait_for_navigation:
            navigation_wait_started = time.monotonic()
            # Let immediate browser events dispatched by the action reach the
            # listeners above. In headed Chromium, PDF navigation/download
            # events can arrive just after mouse.up() even though the URL has
            # already changed.
            await asyncio.sleep(0.05)
            if not nav_started.is_set():
                grace_ms = load_config().tools.browser.waits.post_action_nav_grace_ms
                if grace_ms > 0:
                    try:
                        await asyncio.wait_for(nav_started.wait(), timeout=grace_ms / 1000)
                    except asyncio.TimeoutError:
                        pass
            if nav_started.is_set():
                try:
                    await source_page.wait_for_load_state("domcontentloaded", timeout=10_000)
                except PlaywrightError:
                    pass
            navigation_wait_ms = (time.monotonic() - navigation_wait_started) * 1000

        source_page.remove_listener("response", _on_response)
        source_page.remove_listener("request", _on_request)
        self._context.remove_listener("page", _on_new_page)

        response = captured_responses[-1] if captured_responses else None
        settled_page = source_page

        # A click can open a tab.  When the source page never navigated itself
        # (no document response of its own), that tab is where the agent now is,
        # so work out what landed in it: an ordinary page, which is simply where
        # it went, or a file, which is a download.
        if new_pages and response is None:
            new_page = new_pages[-1]
            # Only this tab's own responses.  The listener appends into this
            # same list, so it stays current across the wait below.
            new_page_responses = responses_by_new_page.get(new_page, [])
            if not new_page_responses:
                try:
                    await new_page.wait_for_load_state(
                        "domcontentloaded",
                        timeout=10_000,
                    )
                except (PlaywrightTimeoutError, PlaywrightError):
                    pass
            # The tab announced what it is — a document response, or a download
            # already under way.  Either way the agent is in it.
            if new_page_responses or self._pending_downloads or self._download_tasks:
                settled_page = new_page
                response = new_page_responses[-1] if new_page_responses else None

            # Nothing announced itself, which does not mean nothing happened.
            # Chrome's PDF viewer (non-headless) renders a file in the new tab
            # while firing neither a response nor a download event, so the only
            # way to know is to fetch the URL ourselves; the probe records a
            # download when it turns out to be a file.
            #
            # Whichever it was, the agent is in the new tab.  Answering with the
            # tab it clicked *from* is what used to make the click look like it
            # did nothing.
            if settled_page is source_page and not self._pending_downloads:
                new_url = getattr(new_page, "url", "")
                if new_url and not new_url.startswith(("about:", "chrome:")):
                    await self._probe_file_url(new_url)
                    settled_page = new_page

        # Clean up response listeners on new pages
        for np, listener in _np_listeners:
            try:
                np.remove_listener("response", listener)
            except Exception:  # noqa: BLE001
                pass

        result = await self._finalize_action(
            settled_page,
            response=response,
            initial_url=initial_url,
            saw_download_response=_saw_download_response,
        )
        result.action_ms = action_ms
        result.navigation_wait_ms = navigation_wait_ms

        # If a download was captured from a new tab, close that tab so the
        # agent returns to the original page rather than receiving a closed or
        # about:blank download tab in the interaction result.
        if result.download and settled_page is not source_page:
            try:
                await settled_page.close()
            except Exception:  # noqa: BLE001
                pass
            # That tab is gone; the agent is back where it started.
            result.tab = source_tab

        return result
