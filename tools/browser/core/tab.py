"""Stable browser-tab identity and document selection."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Frame as PlaywrightFrame
from playwright.async_api import Page

from config import load_config
from tools.browser.core.challenges import ChallengeInfo, detect_challenge
from tools.browser.core.document import Document

if TYPE_CHECKING:
    from playwright.async_api import CDPSession, FileChooser, Response

    from tools.browser.core.rendering import RenderedDocument
    from tools.browser.core.settling import SettleTimings

logger = logging.getLogger(__name__)


class Tab:
    """One browser tab and every piece of state scoped to that tab.

    ``Browser`` owns the collection of tabs and coordinates operations across
    them. ``Tab`` owns identity and document-local state: navigation exclusion,
    challenge state and the embedded document selected for browser tools.

    Playwright's ``Page`` stays behind this boundary as much as possible. Tools
    ask for :meth:`document` or :meth:`render_document`; code that needs physical
    mouse, keyboard, or screenshot access is routed through ``Document`` or a
    focused ``Tab`` method instead of choosing between Page and Frame itself.
    """

    # An embedded document must cover a meaningful part of the viewport before
    # it can replace the root document. The content checks below prevent a large
    # but empty advertising or layout iframe from winning on area alone.
    _CONTENT_FRAME_THRESHOLD = 0.25

    def __init__(self, tab_id: int, page: Page) -> None:
        """Bind an immutable, monotonically allocated ID to a browser page."""
        self._id = tab_id
        self._page = page

        # Only embedded content is cached. ``None`` means the root document is
        # selected or selection must be recomputed.
        self._content_frame: PlaywrightFrame | None = None
        self._document: Document | None = None
        self._challenge: ChallengeInfo | None = None

        # This flag excludes overlapping explicit goto() operations on one tab.
        # Link clicks use the interaction pipeline and do not set it.
        self._navigating = False

    @property
    def id(self) -> int:
        """Return the stable ID exposed to browser-tool callers."""
        return self._id

    @property
    def url(self) -> str:
        """Return the tab's current top-level URL."""
        return self._page.url

    @property
    def challenge(self) -> ChallengeInfo | None:
        """Return the active anti-bot challenge, if one was detected."""
        return self._challenge

    def is_closed(self) -> bool:
        """Return whether the underlying browser tab is closed."""
        return self._page.is_closed()

    async def title(self) -> str:
        """Return the top-level document title, or an empty title during teardown."""
        try:
            return await self._page.title()
        except PlaywrightError:
            return ""

    async def close(self) -> None:
        """Close this browser tab."""
        await self._page.close()

    async def activate(self) -> None:
        """Bring this tab to the front of the browser window."""
        await self._page.bring_to_front()

    async def devtools_session(self) -> CDPSession:
        """Open a DevTools session attached to this tab."""
        return await self._page.context.new_cdp_session(self._page)

    async def evaluate(self, expression: str) -> Any:
        """Evaluate JavaScript in the document currently selected for this tab."""
        return await (await self.document()).evaluate(expression)

    async def go_forward(self) -> None:
        """Move this tab forward in session history."""
        await self._page.go_forward()

    async def reload(self) -> None:
        """Reload this tab."""
        await self._page.reload()

    def subscribe(
        self,
        *,
        on_navigated: Callable[[], None] | None = None,
        on_loaded: Callable[[], None] | None = None,
        on_closed: Callable[[], None] | None = None,
        on_file_chooser: Callable[[FileChooser], None] | None = None,
    ) -> Callable[[], None]:
        """Subscribe to normalized tab events and return an unsubscribe callback.

        Playwright event payloads stay inside ``Tab``. In particular,
        ``on_navigated`` fires only for the root document, so consumers do not
        need to know about Playwright frame identity.
        """
        unsubscribers: list[Callable[[], None]] = []

        if on_navigated is not None:

            def _on_frame(frame: PlaywrightFrame) -> None:
                if frame == self._page.main_frame:
                    on_navigated()

            self._page.on("framenavigated", _on_frame)
            unsubscribers.append(lambda: self._page.remove_listener("framenavigated", _on_frame))
        if on_loaded is not None:

            def _on_load(_page: Page) -> None:
                on_loaded()

            self._page.on("load", _on_load)
            unsubscribers.append(lambda: self._page.remove_listener("load", _on_load))
        if on_closed is not None:

            def _on_close(_page: Page) -> None:
                on_closed()

            self._page.on("close", _on_close)
            unsubscribers.append(lambda: self._page.remove_listener("close", _on_close))
        if on_file_chooser is not None:
            self._page.on("filechooser", on_file_chooser)
            unsubscribers.append(lambda: self._page.remove_listener("filechooser", on_file_chooser))

        def _unsubscribe() -> None:
            for unsubscribe in unsubscribers:
                unsubscribe()

        return _unsubscribe

    async def screenshot(
        self,
        *,
        image_type: str = "png",
        full_page: bool = False,
        quality: int | None = None,
        timeout_ms: int | None = None,
    ) -> bytes:
        """Capture this tab without exposing Playwright's Page requirement."""
        options: dict[str, object] = {
            "type": image_type,
            "full_page": full_page,
        }
        if quality is not None:
            options["quality"] = quality
        if timeout_ms is not None:
            options["timeout"] = timeout_ms
        return await self._page.screenshot(**options)  # type: ignore[arg-type]

    @asynccontextmanager
    async def capture_console(self) -> AsyncIterator[list[str]]:
        """Collect console messages produced within the context.

        Listener setup and teardown belong to the tab because console events
        are page-scoped in Playwright even when JavaScript runs in an embedded
        document.
        """
        lines: list[str] = []

        def _on_console(message: Any) -> None:
            text = message.text
            if text:
                lines.append(text)

        self._page.on("console", _on_console)
        try:
            yield lines
        finally:
            self._page.remove_listener("console", _on_console)

    def _page_for_browser(self) -> Page:
        """Return the Playwright page to Browser orchestration internals."""
        return self._page

    async def document(self) -> Document:
        """Return the document browser tools should inspect and interact with.

        The root document is the default. A large content-bearing ``<iframe>``
        can become the selected document when the surrounding page is merely a
        host for an embedded application. Challenge pages always select the root
        document so tools never enter a verification widget.
        """
        frame = self._content_frame
        if frame is not None and frame.is_detached():
            logger.debug(
                "Selected embedded document for tab=%s detached; selecting again",
                self._id,
            )
            self._invalidate_document()
            frame = None

        if self._document is not None:
            return self._document

        if frame is None:
            frame, challenge = await self._select_frame()
            self._content_frame = frame if frame is not self._page.main_frame else None
            self._challenge = challenge

        self._document = Document(
            frame=frame or self._page.main_frame,
            page=self._page,
        )
        return self._document

    async def render_document(
        self,
        response: Response | None = None,
        *,
        settle: bool = True,
        scope: str | None = None,
        budget: int | None = None,
        full_page: bool = False,
    ) -> RenderedDocument:
        """Render the selected document while protecting its identity.

        One attempt is the linear operation callers care about: select a
        document, optionally settle it, then walk its DOM. Navigation can
        replace that document during either settling or walking, so the whole
        operation retries once when its selected document changes.
        """
        from tools.browser.core.rendering import DEFAULT_BUDGET
        from tools.browser.core.rendering import render_document as render

        waits = load_config().tools.browser.waits
        resolved_budget = DEFAULT_BUDGET if budget is None else budget
        timings: SettleTimings | None = None
        rendered: RenderedDocument | None = None

        # Two attempts are enough to cross one ordinary navigation boundary
        # without hiding a page that changes forever.
        for attempt in range(2):
            document = await self.document()

            # Challenge pages render a routing banner rather than useful DOM;
            # settling them only delays that response.
            if self._challenge is not None:
                rendered = await render(
                    self,
                    document,
                    response,
                    scope=scope,
                    budget=resolved_budget,
                    full_page=full_page,
                    settle_timings=None,
                )
                break

            if settle:
                timings = await document.settle(waits)
                current = await self.document()
                settle_failed = timings.error is not None
                document_changed = document is not current
                if (settle_failed or document_changed) and attempt == 0:
                    continue
                document = current
            else:
                timings = None

            # Redirect responses describe an earlier document. Dropping that
            # response keeps the header aligned with the live tab we walk.
            current_response = response
            if current_response is not None and current_response.url != self.url:
                current_response = None

            rendered = await render(
                self,
                document,
                current_response,
                scope=scope,
                budget=resolved_budget,
                full_page=full_page,
                settle_timings=timings,
            )

            if self.is_closed() or attempt == 1:
                break

            # Rendering stamps interaction refs. If navigation raced the
            # walk, returning those refs would let the next tool target a
            # replacement document with stale identity.
            after_walk = await self.document()
            if document is after_walk:
                break
            rendered = None

        if rendered is None:  # pragma: no cover - loop always builds or retries
            raise RuntimeError("Document rendering retry loop completed without output")
        return rendered

    def _begin_navigation(self) -> None:
        """Mark the start of an explicit Browser.navigate() operation."""
        self._navigating = True

    def _navigation_in_progress(self) -> bool:
        """Return whether an explicit navigation currently owns this tab."""
        return self._navigating

    def _finish_navigation(self) -> None:
        """Release this tab after an explicit Browser.navigate() operation."""
        self._navigating = False

    def _handle_frame_navigated(self, frame: PlaywrightFrame) -> None:
        """Invalidate refs when the root or selected embedded document changes."""
        if frame != self._page.main_frame and frame is not self._content_frame:
            return
        self._invalidate_document()

    def _invalidate_document(self) -> None:
        """Drop document selection and challenge state tied to the old DOM."""
        self._content_frame = None
        self._document = None
        self._challenge = None

    def _set_challenge(self, challenge: ChallengeInfo | None) -> None:
        """Record a challenge, which always forces the root document."""
        changed = challenge != self._challenge
        self._challenge = challenge
        if challenge is not None:
            self._content_frame = None
        if changed:
            self._document = None

    def _set_content_frame(self, frame: PlaywrightFrame | None) -> None:
        """Set the embedded document selected by the content heuristic."""
        if frame is not self._content_frame:
            self._document = None
        self._content_frame = frame

    async def _refresh_content_frame(
        self,
    ) -> tuple[PlaywrightFrame | None, PlaywrightFrame | None]:
        """Re-run selection after an in-page interaction and return its change."""
        previous = self._content_frame
        previous_challenge = self._challenge
        selected = await self._detect_embedded_content_frame()
        self._challenge = None
        self._content_frame = selected
        if selected is not previous or previous_challenge is not None:
            self._document = None
        return previous, selected

    async def _select_frame(
        self,
    ) -> tuple[PlaywrightFrame, ChallengeInfo | None]:
        """Select the root frame or a content-bearing embedded frame."""
        # Challenge detection runs first because a large verification iframe
        # must never be mistaken for the application's content document.
        challenge = await detect_challenge(self._page)
        if challenge is not None:
            return self._page.main_frame, challenge

        try:
            selected = await self._detect_embedded_content_frame()
        except Exception:  # noqa: BLE001 - selection is best-effort
            selected = None
        return selected or self._page.main_frame, None

    async def _detect_embedded_content_frame(self) -> PlaywrightFrame | None:
        """Return the largest accessible content iframe covering the viewport."""
        try:
            window_size = await self._page.evaluate("() => ({ width: window.innerWidth, height: window.innerHeight })")
        except PlaywrightError:
            return None
        width, height = window_size.get("width", 0), window_size.get("height", 0)
        if not width or not height:
            return None
        minimum_area = width * height * self._CONTENT_FRAME_THRESHOLD

        selected: PlaywrightFrame | None = None
        selected_area = 0.0

        for frame in self._page.frames:
            if frame == self._page.main_frame or frame.is_detached():
                continue
            try:
                element = await frame.frame_element()
                box = await element.bounding_box()
            except Exception:  # noqa: BLE001 - skip inaccessible frames
                continue
            if box is None:
                continue

            area = box["width"] * box["height"]
            if area < minimum_area:
                continue

            try:
                content = await frame.evaluate(
                    """() => {
                        if (!document.body) return { children: 0, text: 0, interactive: 0 };
                        return {
                            children: document.body.children.length,
                            text: (document.body.innerText || '').trim().length,
                            interactive: document.body.querySelectorAll(
                                'a[href], button, input, select, textarea'
                            ).length,
                        };
                    }"""
                )
            except Exception:  # noqa: BLE001 - cross-origin or detached
                continue

            has_content = content["children"] > 0 and (content["text"] > 0 or content["interactive"] > 3)
            if has_content and area > selected_area:
                selected = frame
                selected_area = area

        return selected


__all__ = ["Tab"]
