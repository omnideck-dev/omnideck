"""Translate visual-grounding responses into browser input actions.

Translates a ``GroundingResponse`` into the appropriate ``human_*`` browser
function call.
"""

from __future__ import annotations

import asyncio
import logging

from tools._grounding import GroundingResponse
from tools.browser.core.document import Document
from tools.browser.core.exceptions import BrowserToolError

logger = logging.getLogger(__name__)

# Half-size (pixels) of the synthetic bounding box built around the
# single-point coordinates returned by UI-TARS.
_POINT_BBOX_HALF = 5

# Maps TARS modifier names to Playwright key names.
_HOTKEY_MAP: dict[str, str] = {
    "ctrl": "Control",
    "control": "Control",
    "alt": "Alt",
    "shift": "Shift",
    "meta": "Meta",
    "win": "Meta",
    "cmd": "Meta",
    "command": "Meta",
    "super": "Meta",
    "esc": "Escape",
    "escape": "Escape",
    "enter": "Enter",
    "return": "Enter",
    "tab": "Tab",
    "backspace": "Backspace",
    "delete": "Delete",
    "del": "Delete",
    "space": " ",
    "up": "ArrowUp",
    "down": "ArrowDown",
    "left": "ArrowLeft",
    "right": "ArrowRight",
    "arrowup": "ArrowUp",
    "arrowdown": "ArrowDown",
    "arrowleft": "ArrowLeft",
    "arrowright": "ArrowRight",
    "pageup": "PageUp",
    "pagedown": "PageDown",
    "home": "Home",
    "end": "End",
}


def _normalize_hotkey(tars_key: str) -> str:
    """Convert a TARS hotkey string to Playwright format.

    Examples:
        ``"ctrl+c"`` → ``"Control+c"``
        ``"Ctrl+Shift+P"`` → ``"Control+Shift+P"``
        ``"esc"`` → ``"Escape"``
    """
    parts = tars_key.split("+")
    normalized: list[str] = []
    for part in parts:
        stripped = part.strip()
        mapped = _HOTKEY_MAP.get(stripped.lower())
        normalized.append(mapped if mapped is not None else stripped)
    return "+".join(normalized)


def _point_bbox(x: int, y: int) -> tuple[int, int, int, int]:
    """Build a small bounding box around a point for human_* functions."""
    return (
        x - _POINT_BBOX_HALF,
        y - _POINT_BBOX_HALF,
        x + _POINT_BBOX_HALF,
        y + _POINT_BBOX_HALF,
    )


def _require_coords(response: GroundingResponse) -> tuple[int, int]:
    """Extract x, y from response, raising if absent."""
    if response.x is None or response.y is None:
        msg = f"Action '{response.action_type}' requires coordinates but none were returned"
        raise BrowserToolError(msg, tool="browser_visual_action")
    return response.x, response.y


async def execute_action(
    response: GroundingResponse,
    document: Document,
) -> None:
    """Dispatch a ``GroundingResponse`` to the appropriate ``human_*`` function.

    Args:
        response: Parsed grounding response from UI-TARS.
        document: Selected DOM context; input is routed to its owning tab.

    Raises:
        BrowserToolError: On unknown action types or missing data.
    """
    action = response.action_type

    if action == "click":
        x, y = _require_coords(response)
        bbox = _point_bbox(x, y)
        await document.click_at(bbox)

    elif action == "left_double":
        x, y = _require_coords(response)
        bbox = _point_bbox(x, y)
        await document.double_click_at(bbox)

    elif action == "right_single":
        x, y = _require_coords(response)
        bbox = _point_bbox(x, y)
        await document.right_click_at(bbox)

    elif action == "drag":
        # Drag has two coordinate pairs: source and destination.
        coords = response.raw.get("coordinates", [])
        if len(coords) < 2:
            msg = "Drag action requires two coordinate pairs"
            raise BrowserToolError(msg, tool="browser_visual_action")
        src = coords[0]["screen"]
        dst = coords[1]["screen"]
        src_bbox = _point_bbox(src[0], src[1])
        dst_bbox = _point_bbox(dst[0], dst[1])
        await document.drag_at(src_bbox, dst_bbox)

    elif action == "type":
        content = response.raw.get("type_content", "")
        if content:
            await document.type_focused(content)

    elif action == "hotkey":
        raw_key = response.raw.get("hotkey", "")
        if not raw_key:
            msg = "Hotkey action missing 'hotkey' field"
            raise BrowserToolError(msg, tool="browser_visual_action")
        normalized = _normalize_hotkey(raw_key)
        await document.press_keys([normalized])

    elif action == "scroll":
        direction = response.raw.get("scroll_direction", "down")
        await document.scroll(direction)

    elif action == "wait":
        await asyncio.sleep(1.0)

    elif action == "finished":
        # No-op — caller handles finished state.
        pass

    else:
        logger.warning("Unsupported action type from grounding model: %s", action)
