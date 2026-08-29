"""Human-like scrolling for selected browser documents."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Frame, Page

from tools.browser.core.exceptions import BrowserToolError
from tools.browser.core.input._shared import _sleep_ms
from tools.browser.core.modals import MODAL_HELPERS_JS


@dataclass(frozen=True, slots=True)
class ScrollOutcome:
    """Observable result of one selected-document scroll attempt."""

    moved: bool
    blocked_by_modal: bool = False


_INITIAL_SCROLL_STATE_JS = """
({ x, y }) => {
__MODAL_HELPERS__

  const activeModal = omnideckActiveModal();
  const modalScrollTarget = activeModal
    ? omnideckScrollableModalElement(activeModal)
    : null;
  let scrollTarget = x === null || y === null
    ? null
    : document.elementFromPoint(x, y);
  while (scrollTarget && scrollTarget !== document.body
      && scrollTarget !== document.documentElement) {
    if (scrollTarget.scrollHeight > scrollTarget.clientHeight + 1) break;
    scrollTarget = scrollTarget.parentElement;
  }
  if (scrollTarget === document.body || scrollTarget === document.documentElement) {
    scrollTarget = null;
  }
  if (modalScrollTarget) scrollTarget = modalScrollTarget;

  const targetRect = modalScrollTarget?.getBoundingClientRect() || null;
  return {
    windowY: window.scrollY,
    targetScrollTop: scrollTarget?.scrollTop ?? null,
    modalOpen: Boolean(activeModal),
    modalScrollable: Boolean(modalScrollTarget),
    modalTargetPoint: targetRect ? {
      x: targetRect.left + targetRect.width / 2,
      y: targetRect.top + Math.min(targetRect.height / 2, window.innerHeight / 2)
    } : null
  };
}
""".replace("__MODAL_HELPERS__", MODAL_HELPERS_JS)

_SCROLL_MODAL_JS = """
({ direction, delta }) => {
__MODAL_HELPERS__

  const activeModal = omnideckActiveModal();
  const target = activeModal
    ? omnideckScrollableModalElement(activeModal)
    : null;
  if (!target) return false;

  if (direction === 'top') {
    target.scrollTo(0, 0);
  } else if (direction === 'bottom') {
    target.scrollTo(0, target.scrollHeight);
  } else if (direction === 'page_down' || direction === 'page_up') {
    target.scrollBy(0, target.clientHeight * (direction === 'page_down' ? 1 : -1));
  } else {
    target.scrollBy(0, delta);
  }
  return true;
}
""".replace("__MODAL_HELPERS__", MODAL_HELPERS_JS)

_FINALIZE_SCROLL_JS = """
({ initial }) => {
__MODAL_HELPERS__

  const activeModal = omnideckActiveModal();
  const modalScrollTarget = activeModal
    ? omnideckScrollableModalElement(activeModal)
    : null;
  let scrollTarget = initial.x === null || initial.y === null
    ? null
    : document.elementFromPoint(initial.x, initial.y);
  while (scrollTarget && scrollTarget !== document.body
      && scrollTarget !== document.documentElement) {
    if (scrollTarget.scrollHeight > scrollTarget.clientHeight + 1) break;
    scrollTarget = scrollTarget.parentElement;
  }
  if (scrollTarget === document.body || scrollTarget === document.documentElement) {
    scrollTarget = null;
  }
  if (modalScrollTarget) scrollTarget = modalScrollTarget;

  const targetContainerMoved = initial.targetScrollTop !== null
    && scrollTarget
    && scrollTarget.scrollTop !== initial.targetScrollTop;
  if (window.scrollY !== initial.windowY || targetContainerMoved) {
    return { moved: true, blockedByModal: false };
  }

  if (activeModal) {
    return {
      moved: false,
      blockedByModal: !modalScrollTarget
    };
  }

  return {
    moved: false,
    blockedByModal: false
  };
}
""".replace("__MODAL_HELPERS__", MODAL_HELPERS_JS)


async def _wheel_target_point(frame: Frame, page: Page) -> tuple[float, float]:
    """Aim wheel input and return its coordinates inside the selected document."""
    if frame == page.main_frame:
        from tools.browser.core.input.pointer import _last_pointer_position

        x, y = _last_pointer_position(page, fallback=(0, 0))
        return float(x), float(y)

    frame_element = await frame.frame_element()
    box = await frame_element.bounding_box()
    if box is None or box["width"] <= 0 or box["height"] <= 0:
        raise BrowserToolError(
            "selected document is not visible for wheel scrolling",
            tool="scroll_page",
        )

    from tools.browser.core.input.pointer import _mouse_move_with_fake_cursor

    await _mouse_move_with_fake_cursor(
        page,
        x=box["x"] + box["width"] / 2,
        y=box["y"] + box["height"] / 2,
    )
    return box["width"] / 2, box["height"] / 2


async def _move_to_document_point(
    frame: Frame,
    page: Page,
    *,
    x: float,
    y: float,
) -> None:
    """Move physical input to document-relative coordinates."""
    page_x = x
    page_y = y
    if frame != page.main_frame:
        frame_element = await frame.frame_element()
        box = await frame_element.bounding_box()
        if box is None:
            raise BrowserToolError(
                "selected document is not visible for wheel scrolling",
                tool="scroll_page",
            )
        page_x += box["x"]
        page_y += box["y"]

    from tools.browser.core.input.pointer import _mouse_move_with_fake_cursor

    await _mouse_move_with_fake_cursor(page, x=page_x, y=page_y)


async def human_scroll(
    frame: Frame,
    page: Page,
    direction: str = "down",
    amount: int | None = None,
) -> ScrollOutcome:
    """Scroll the selected document with human-like wheel increments."""
    if not isinstance(direction, str) or not direction:
        raise BrowserToolError("direction must be a non-empty string", tool="scroll_page")

    normalized = direction.lower()
    allowed = {"down", "up", "page_down", "page_up", "top", "bottom"}
    if normalized not in allowed:
        raise BrowserToolError(f"Invalid scroll direction '{direction}'", tool="scroll_page")

    try:
        delta = 0
        wheel_target: tuple[float, float] | None = None

        if normalized in {"down", "up"}:
            if amount is None:
                try:
                    height = await frame.evaluate("() => window.innerHeight")
                    if not isinstance(height, int | float) or height <= 0:
                        height = 800
                except PlaywrightError:
                    height = 800
                delta = round(height) if normalized == "down" else -round(height)
            else:
                if not isinstance(amount, int):
                    raise BrowserToolError("amount must be an integer number of pixels", tool="scroll_page")
                delta = amount if normalized == "down" else -amount
            delta += random.randint(-4, 4)

            if hasattr(page, "mouse") and page.mouse is not None:
                wheel_target = await _wheel_target_point(frame, page)

        initial_state = await frame.evaluate(
            _INITIAL_SCROLL_STATE_JS,
            {
                "x": wheel_target[0] if wheel_target is not None else None,
                "y": wheel_target[1] if wheel_target is not None else None,
            },
        )
        if not isinstance(initial_state, dict):
            initial_state = {
                "windowY": 0,
                "targetScrollTop": None,
                "modalOpen": False,
                "modalScrollable": False,
            }
        initial_state["x"] = wheel_target[0] if wheel_target is not None else None
        initial_state["y"] = wheel_target[1] if wheel_target is not None else None

        modal_open = initial_state.get("modalOpen") is True
        modal_scrollable = initial_state.get("modalScrollable") is True
        modal_target = initial_state.get("modalTargetPoint")

        if normalized in {"down", "up"} and modal_scrollable and isinstance(modal_target, dict):
            await _move_to_document_point(
                frame,
                page,
                x=float(modal_target["x"]),
                y=float(modal_target["y"]),
            )

        if modal_open and not modal_scrollable:
            pass
        elif modal_open and normalized in {"top", "bottom", "page_down", "page_up"}:
            await frame.evaluate(
                _SCROLL_MODAL_JS,
                {"direction": normalized, "delta": delta},
            )
        elif normalized in {"top", "bottom"}:
            await frame.evaluate(
                "(bottom) => window.scrollTo(0, bottom ? document.documentElement.scrollHeight : 0)",
                normalized == "bottom",
            )
        elif normalized in {"page_down", "page_up"}:
            await frame.evaluate(
                "(direction) => window.scrollBy(0, window.innerHeight * direction)",
                1 if normalized == "page_down" else -1,
            )
        else:
            if not hasattr(page, "mouse") or page.mouse is None:
                if modal_open:
                    await frame.evaluate(
                        _SCROLL_MODAL_JS,
                        {"direction": normalized, "delta": delta},
                    )
                else:
                    await frame.evaluate(
                        "(dy) => window.scrollBy({ top: dy, left: 0, behavior: 'smooth' })",
                        delta,
                    )
            else:
                wheel_increment = 50 if delta > 0 else -50
                remaining = abs(delta)
                events_count = max(1, remaining // abs(wheel_increment))
                for _ in range(int(events_count)):
                    await page.mouse.wheel(0, wheel_increment)
                    await asyncio.sleep(0.016)
                remainder = remaining % abs(wheel_increment)
                if remainder > 0:
                    await page.mouse.wheel(0, remainder if delta > 0 else -remainder)
                    await asyncio.sleep(0.016)

        raw_outcome = await frame.evaluate(
            _FINALIZE_SCROLL_JS,
            {
                "initial": initial_state,
            },
        )
        await _sleep_ms(random.randint(100, 300))
        if not isinstance(raw_outcome, dict):
            return ScrollOutcome(moved=False)
        return ScrollOutcome(
            moved=raw_outcome.get("moved") is True,
            blocked_by_modal=raw_outcome.get("blockedByModal") is True,
        )
    except Exception as exc:
        raise BrowserToolError(f"Failed to perform scroll: {exc}", tool="scroll_page") from exc


__all__ = ["ScrollOutcome", "human_scroll"]
