"""Human-like scrolling for selected browser documents."""

from __future__ import annotations

import asyncio
import random

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Frame, Page

from tools.browser.core.exceptions import BrowserToolError
from tools.browser.core.input._shared import _sleep_ms


async def _move_mouse_into_frame(frame: Frame, page: Page) -> None:
    """Aim wheel input inside a selected embedded document."""
    if frame == page.main_frame:
        return

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
            if not hasattr(page, "mouse") or page.mouse is None:
                await frame.evaluate(
                    "(dy) => window.scrollBy({ top: dy, left: 0, behavior: 'smooth' })",
                    delta,
                )
            else:
                await _move_mouse_into_frame(frame, page)
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

        await _sleep_ms(random.randint(100, 300))
    except Exception as exc:
        raise BrowserToolError(f"Failed to perform scroll: {exc}", tool="scroll_page") from exc


__all__ = ["human_scroll"]
