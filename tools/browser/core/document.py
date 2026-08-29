"""The document browser tools read and the page used for physical input."""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Frame as PlaywrightFrame
from playwright.async_api import Locator, Page

from tools.browser.core.exceptions import BrowserToolError
from tools.browser.core.input.scroll import ScrollOutcome, human_scroll

if TYPE_CHECKING:
    from config import BrowserWaitConfig
    from tools.browser.core.settling import SettleTimings


_NO_ARGUMENT = object()
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResolvedElement:
    """An opaque element ref resolved inside one specific Document."""

    ref: str
    _document: Document
    _locator: Locator


class Document:
    """A selected browser document with DOM and input routing kept together.

    Playwright exposes DOM operations on ``Frame`` but mouse and keyboard input
    on the owning ``Page``. Browser tools should not need to remember that
    distinction. ``Document`` keeps both handles private and exposes the
    document-level operations used by browser tools.

    It is intentionally a short-lived value owned by ``Tab`` rather than a
    second source of mutable tab state. Its object identity is the document
    identity: when navigation or embedded-document selection changes, the Tab
    replaces this object.
    """

    def __init__(
        self,
        *,
        frame: PlaywrightFrame,
        page: Page,
    ) -> None:
        """Bind the selected DOM frame to its owning physical-input page."""
        self._frame = frame
        self._page = page

    async def evaluate(
        self,
        expression: str,
        arg: Any = _NO_ARGUMENT,
    ) -> Any:
        """Evaluate JavaScript in this document's DOM context."""
        if arg is _NO_ARGUMENT:
            return await self._frame.evaluate(expression)
        return await self._frame.evaluate(expression, arg)

    async def content(self) -> str:
        """Return this document's serialized HTML."""
        return await self._frame.content()

    async def resolve_ref(self, ref: str, *, tool_name: str) -> ResolvedElement:
        """Resolve one agent-visible numeric ref inside this document.

        Args:
            ref: Numeric ref returned by ``browse_page()``.
            tool_name: Agent tool name used in errors.

        Returns:
            The unique element carrying that ref.

        Raises:
            BrowserToolError: If the ref is invalid, stale, or ambiguous.
        """
        clean = ref.strip()
        if not clean or not clean.isdecimal():
            raise BrowserToolError(
                "value must be a numeric ref from browse_page()",
                tool=tool_name,
            )

        ref_number = int(clean)
        selector = f'[data-ct-ref="{ref_number}"]'
        locator = self._frame.locator(selector)
        try:
            count = await locator.count()
        except PlaywrightError as exc:
            logger.debug("Ref lookup failed for %s: %s", ref_number, exc)
            raise BrowserToolError(
                f"Unable to resolve ref {ref_number}. Call browse_page() for fresh refs.",
                tool=tool_name,
            ) from exc

        if count == 0:
            raise BrowserToolError(
                f"Ref {ref_number} not found. The document may have changed; call browse_page() for fresh refs.",
                tool=tool_name,
            )
        if count > 1:
            raise BrowserToolError(
                f"Ref {ref_number} matched {count} elements. Call browse_page() to rebuild the document refs.",
                tool=tool_name,
            )
        return ResolvedElement(
            ref=str(ref_number),
            _document=self,
            _locator=locator.first,
        )

    def _locator_for(self, element: ResolvedElement) -> Locator:
        """Return an element's locator after checking document ownership."""
        if element._document is not self:
            raise BrowserToolError(
                f"Ref {element.ref} belongs to a document that is no longer selected. "
                "Call browse_page() for fresh refs.",
                tool="browser",
            )
        return element._locator

    async def click(self, element: ResolvedElement) -> None:
        """Click an element using physical pointer input."""
        from tools.browser.core.input.pointer import human_click

        await human_click(self._page, self._locator_for(element))

    async def press_and_hold(self, element: ResolvedElement, *, duration_ms: int) -> None:
        """Hold physical pointer input on an element for a duration."""
        from tools.browser.core.input.pointer import human_press_and_hold

        await human_press_and_hold(
            self._page,
            self._locator_for(element),
            duration_ms=duration_ms,
        )

    async def drag(self, source: ResolvedElement, target: ResolvedElement) -> None:
        """Drag between two elements using physical pointer input."""
        from tools.browser.core.input.pointer import human_drag

        await human_drag(
            self._page,
            self._locator_for(source),
            target_locator=self._locator_for(target),
        )

    async def type_text(
        self,
        element: ResolvedElement,
        text: str,
        *,
        clear_existing: bool = True,
    ) -> None:
        """Type text with physical keyboard input."""
        from tools.browser.core.input.keyboard import human_type

        await human_type(
            self._page,
            self._locator_for(element),
            text,
            clear_existing=clear_existing,
        )

    async def fill_field(self, element: ResolvedElement, value: str) -> None:
        """Validate an editable element, focus it, and replace its value."""
        locator = self._locator_for(element)
        tag_name = ""
        input_type = ""
        is_contenteditable = False
        try:
            handle = await locator.element_handle(timeout=5000)
            if handle is not None:
                tag_name = await handle.evaluate("el => el.tagName.toLowerCase()")
                if tag_name == "input":
                    raw_type = await handle.get_attribute("type")
                    input_type = (raw_type or "text").lower()
                is_contenteditable = await handle.evaluate("el => el.isContentEditable")
        except PlaywrightError as exc:  # pragma: no cover - best-effort metadata
            logger.debug("Failed to inspect ref %s for fill_field: %s", element.ref, exc)

        if tag_name not in {"input", "textarea"} and not is_contenteditable:
            raise BrowserToolError(
                "fill_field only supports input, textarea, and contenteditable elements",
                tool="fill_field",
                details={"ref": element.ref},
            )

        unsupported_inputs = {
            "checkbox",
            "radio",
            "submit",
            "button",
            "image",
            "file",
            "hidden",
        }
        if tag_name == "input" and input_type in unsupported_inputs:
            raise BrowserToolError(
                f"Input type '{input_type}' is not supported by fill_field.",
                tool="fill_field",
                details={"ref": element.ref},
            )

        try:
            await self.click(element)
        except PlaywrightError:
            await locator.click(force=True, timeout=5000)
        await self.type_text(element, value, clear_existing=True)

    async def select_option(
        self,
        element: ResolvedElement,
        value: str,
        *,
        wait_after_select_ms: int | None = None,
    ) -> None:
        """Choose a native select option while keeping Playwright details private."""
        locator = self._locator_for(element)
        options = [option.strip() for option in await locator.locator("option").all_text_contents()]
        try:
            target_index = options.index(value)
        except ValueError as exc:
            raise BrowserToolError(
                f"Option '{value}' not found in dropdown. Available options: {options}",
                tool="select_option",
                details={"ref": element.ref},
            ) from exc

        handle = await locator.element_handle(timeout=5000)
        await self.click(element)
        await asyncio.sleep(random.randint(100, 300) / 1000)

        keyboard_succeeded = await self._select_option_with_keyboard(
            handle,
            target_index,
        )
        if not keyboard_succeeded:
            logger.debug("Falling back to JS selectedIndex for '%s'", value)
            await self._select_option_with_javascript(handle, target_index)
            await self.press_keys(["Escape"])

        if wait_after_select_ms:
            await asyncio.sleep(wait_after_select_ms / 1000)

    async def _select_option_with_keyboard(
        self,
        handle: Any,
        target_index: int,
    ) -> bool:
        """Try trusted keyboard selection before falling back to JavaScript."""
        max_steps = 30
        if target_index > max_steps:
            return False
        try:
            await self.press_keys(["Home"])
            await asyncio.sleep(random.randint(30, 80) / 1000)
            for _ in range(target_index):
                await self.press_keys(["ArrowDown"])
                await asyncio.sleep(random.randint(20, 60) / 1000)
            await self.press_keys(["Enter"])
            await asyncio.sleep(random.randint(50, 150) / 1000)
            actual_index = await handle.evaluate("el => el.selectedIndex")
            return bool(actual_index == target_index)
        except Exception as exc:  # noqa: BLE001 - JS is the intended fallback
            logger.debug("Keyboard selection failed: %s", exc)
            return False

    @staticmethod
    async def _select_option_with_javascript(handle: Any, target_index: int) -> None:
        """Set selectedIndex and dispatch the native form events."""
        await handle.evaluate(
            """(el, idx) => {
                el.selectedIndex = idx;
                try {
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                } catch (_) {}
            }""",
            target_index,
        )

    async def screenshot(self, element: ResolvedElement) -> bytes:
        """Capture the element represented by one agent ref."""
        return await self._locator_for(element).screenshot(type="png")

    async def type_focused(self, text: str) -> None:
        """Type text into the currently focused control."""
        from tools.browser.core.input.keyboard import human_type_text

        await human_type_text(self._page, text)

    async def press_keys(self, keys: list[str]) -> None:
        """Press keyboard keys or modifier chords in order."""
        from tools.browser.core.input.keyboard import human_press_keys

        await human_press_keys(self._page, keys)

    async def scroll(self, direction: str, amount: int | None = None) -> ScrollOutcome:
        """Scroll this document using its DOM and owning physical pointer."""
        return await human_scroll(self._frame, self._page, direction=direction, amount=amount)

    async def click_at(self, bounds: tuple[float, float, float, float]) -> None:
        """Click inside document-relative bounds."""
        from tools.browser.core.input.pointer import human_click_at

        await human_click_at(self._page, *bounds)

    async def double_click_at(self, bounds: tuple[float, float, float, float]) -> None:
        """Double-click inside document-relative bounds."""
        from tools.browser.core.input.pointer import human_double_click_at

        await human_double_click_at(self._page, *bounds)

    async def right_click_at(self, bounds: tuple[float, float, float, float]) -> None:
        """Right-click inside document-relative bounds."""
        from tools.browser.core.input.pointer import human_right_click_at

        await human_right_click_at(self._page, *bounds)

    async def drag_at(
        self,
        source_bounds: tuple[float, float, float, float],
        target_bounds: tuple[float, float, float, float],
    ) -> None:
        """Drag between two document-relative bounding boxes."""
        from tools.browser.core.input.pointer import human_drag_at

        await human_drag_at(self._page, *source_bounds, *target_bounds)

    async def settle(self, waits: BrowserWaitConfig) -> SettleTimings:
        """Wait for this document to become stable enough to inspect."""
        from tools.browser.core.settling import _settle_frame

        return await _settle_frame(self._frame, waits=waits)


__all__ = ["Document", "ResolvedElement"]
