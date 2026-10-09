"""Human-like keyboard input for browser documents."""

from __future__ import annotations

import random

from playwright.async_api import Locator, Page

from browser.core.exceptions import BrowserToolError
from browser.core.input._shared import _get_human_config, _sleep_ms


async def human_type(
    page: Page,
    locator: Locator,
    text: str,
    *,
    clear_existing: bool = True,
) -> None:
    """Type text into a focused element with human-like delays."""
    del locator  # Focus is established by the pointer action before typing.
    cfg = _get_human_config()

    if not hasattr(page, "keyboard") or page.keyboard is None:
        raise BrowserToolError("Provided page has no keyboard available", tool="fill_field")

    keyboard = page.keyboard
    if clear_existing:
        try:
            await keyboard.press("Control+A")
            await keyboard.press("Backspace")
        except Exception as exc:
            raise BrowserToolError("Failed to clear existing text via keyboard", tool="fill_field") from exc

    for idx, char in enumerate(text):
        await keyboard.type(char)
        await _sleep_ms(random.randint(cfg.delay_min_ms, cfg.delay_max_ms))
        if cfg.extra_pause_every_chars > 0 and (idx + 1) % cfg.extra_pause_every_chars == 0:
            await _sleep_ms(random.randint(cfg.extra_pause_min_ms, cfg.extra_pause_max_ms))


async def human_type_text(page: Page, text: str) -> None:
    """Type into the focused control without exposing Page.keyboard to callers."""
    if not hasattr(page, "keyboard") or page.keyboard is None:
        raise BrowserToolError("Provided tab has no keyboard available", tool="type")
    cfg = _get_human_config()
    await page.keyboard.type(text, delay=random.randint(cfg.delay_min_ms, cfg.delay_max_ms))


async def human_press_keys(page: Page, keys: list[str]) -> None:
    """Press keys in order, including modifier chords such as Control+Shift+P."""
    if not isinstance(keys, list) or len(keys) == 0:
        raise BrowserToolError("keys must be a non-empty list of key names", tool="press_keys")
    if not hasattr(page, "keyboard") or page.keyboard is None:
        raise BrowserToolError("Provided page has no keyboard available", tool="press_keys")

    for key in keys:
        if not isinstance(key, str) or not key:
            raise BrowserToolError("Each key must be a non-empty string", tool="press_keys")
        parts = key.split("+")
        modifiers = parts[:-1]
        base = parts[-1]
        try:
            for modifier in modifiers:
                await page.keyboard.down(modifier)
                await _sleep_ms(random.randint(0, 10))
            await page.keyboard.press(base)
            for modifier in reversed(modifiers):
                await page.keyboard.up(modifier)
                await _sleep_ms(random.randint(0, 10))
        except Exception as exc:
            raise BrowserToolError(f"Failed to press key '{key}': {exc}", tool="press_keys") from exc


__all__ = ["human_press_keys", "human_type", "human_type_text"]
