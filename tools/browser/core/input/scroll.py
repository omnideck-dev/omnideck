"""Human-like scrolling for selected browser documents."""

from __future__ import annotations

import asyncio
import random

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Frame, Page

from tools.browser.core.exceptions import BrowserToolError
from tools.browser.core.input._shared import _sleep_ms


_INITIAL_SCROLL_STATE_JS = """
({ x, y }) => {
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
  const bodyStyle = document.body ? getComputedStyle(document.body) : null;
  return {
    windowY: window.scrollY,
    targetScrollTop: scrollTarget?.scrollTop ?? null,
    canFallback: Boolean(
      document.body
      && document.body.scrollHeight > window.innerHeight + 1
      && (bodyStyle.overflowY === 'hidden' || bodyStyle.overflowY === 'clip')
    )
  };
}
"""

_FALLBACK_SCROLL_JS = """
({ initial, direction, delta }) => {
  const applyScroll = () => {
    if (direction === 'top') {
      window.scrollTo(0, 0);
    } else if (direction === 'bottom') {
      window.scrollTo(0, Math.max(
        document.scrollingElement?.scrollHeight || 0,
        document.body?.scrollHeight || 0
      ));
    } else if (direction === 'page_down' || direction === 'page_up') {
      window.scrollBy(0, window.innerHeight * (direction === 'page_down' ? 1 : -1));
    } else {
      window.scrollBy(0, delta);
    }
  };

  // Trusted input remains the primary path. Only intervene when it produced
  // no document or targeted-container movement.
  let scrollTarget = initial.x === null || initial.y === null
    ? null
    : document.elementFromPoint(initial.x, initial.y);
  while (scrollTarget && scrollTarget !== document.body
      && scrollTarget !== document.documentElement) {
    if (scrollTarget.scrollHeight > scrollTarget.clientHeight + 1) break;
    scrollTarget = scrollTarget.parentElement;
  }
  const targetContainerMoved = initial.targetScrollTop !== null
    && scrollTarget
    && scrollTarget.scrollTop !== initial.targetScrollTop;
  if (window.scrollY !== initial.windowY || targetContainerMoved) return;

  applyScroll();
  if (window.scrollY !== initial.windowY) return;

  const body = document.body;
  if (!body) return;

  const movingDown = direction === 'down'
    || direction === 'page_down'
    || direction === 'bottom';
  const bodyStyle = getComputedStyle(body);
  const bodyIsTaller = body.scrollHeight > window.innerHeight + 1;
  const bodyLocksOverflow = bodyStyle.overflowY === 'hidden'
    || bodyStyle.overflowY === 'clip';
  if (!movingDown || !bodyIsTaller || !bodyLocksOverflow) return;

  // Common modal/paywall scroll locks fix the body in place as well as hiding
  // overflow. Releasing only one leaves the document unable to scroll.
  const lockedOffset = bodyStyle.position === 'fixed'
    ? Math.max(0, -(parseFloat(bodyStyle.top) || 0))
    : window.scrollY;
  body.style.setProperty('overflow', 'visible', 'important');
  if (bodyStyle.position === 'fixed') {
    body.style.setProperty('position', 'static', 'important');
    body.style.removeProperty('top');
  }
  if (lockedOffset > 0) window.scrollTo(0, lockedOffset);
  applyScroll();
}
"""


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


async def human_scroll(
    frame: Frame,
    page: Page,
    direction: str = "down",
    amount: int | None = None,
) -> None:
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
            initial_state = {"windowY": 0, "targetScrollTop": None, "canFallback": False}
        initial_state["x"] = wheel_target[0] if wheel_target is not None else None
        initial_state["y"] = wheel_target[1] if wheel_target is not None else None

        if normalized in {"top", "bottom"}:
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

        if initial_state.get("canFallback") is True:
            await frame.evaluate(
                _FALLBACK_SCROLL_JS,
                {
                    "initial": initial_state,
                    "direction": normalized,
                    "delta": delta,
                },
            )
        await _sleep_ms(random.randint(100, 300))
    except Exception as exc:
        raise BrowserToolError(f"Failed to perform scroll: {exc}", tool="scroll_page") from exc


__all__ = ["human_scroll"]
