"""Configuration and routing shared by browser input implementations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from config import load_config


@dataclass
class _HumanConfig:
    move_duration_min_ms: int
    move_duration_max_ms: int
    hover_min_ms: int
    hover_max_ms: int
    click_hold_min_ms: int
    click_hold_max_ms: int
    delay_min_ms: int
    delay_max_ms: int
    extra_pause_every_chars: int
    extra_pause_min_ms: int
    extra_pause_max_ms: int


_config_cache: _HumanConfig | None = None


def _get_human_config() -> _HumanConfig:
    global _config_cache
    if _config_cache is None:
        cfg = load_config().tools.browser.human
        pointer = cfg.pointer
        typing = cfg.typing
        _config_cache = _HumanConfig(
            move_duration_min_ms=max(0, pointer.move_duration_min_ms),
            move_duration_max_ms=max(
                0,
                pointer.move_duration_min_ms,
                pointer.move_duration_max_ms,
            ),
            hover_min_ms=max(0, pointer.hover_min_ms),
            hover_max_ms=max(pointer.hover_min_ms, pointer.hover_max_ms),
            click_hold_min_ms=max(0, pointer.click_hold_min_ms),
            click_hold_max_ms=max(pointer.click_hold_min_ms, pointer.click_hold_max_ms),
            delay_min_ms=max(0, typing.delay_min_ms),
            delay_max_ms=max(typing.delay_min_ms, typing.delay_max_ms),
            extra_pause_every_chars=max(typing.extra_pause_every_chars, 0),
            extra_pause_min_ms=max(0, typing.extra_pause_min_ms),
            extra_pause_max_ms=max(typing.extra_pause_min_ms, typing.extra_pause_max_ms),
        )
    return _config_cache


async def _sleep_ms(duration_ms: int) -> None:
    if duration_ms > 0:
        await asyncio.sleep(duration_ms / 1000.0)
