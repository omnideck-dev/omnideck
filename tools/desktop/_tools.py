"""Desktop interaction tools for the desktop agent.

Provides two observation tools:
- read_screen() — fast a11y tree listing interactive elements with coordinates
- describe_screen() — vision model description of what's visible on screen

Action tools (mouse/keyboard) return the a11y tree after each action.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import shlex
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console

from tools.desktop._exec import _run_desktop_cmd
from tools.desktop._lifecycle import ensure_desktop_running
from tools.desktop._screenshot import capture_screenshot

logger = logging.getLogger(__name__)

# Post-action settle delay before observation
_SETTLE_DELAY_S = 2.0

# Lazy-initialised Rich console for panel logging.
_console: Console | None = None


def _get_console() -> Console:
    global _console  # noqa: PLW0603
    if _console is None:
        from rich.console import Console
        _console = Console(stderr=True)
    return _console


def _log_desktop_panel(
    tool_name: str,
    *,
    elements: list[dict],
    args: str = "",
    elapsed_ms: float = 0,
) -> None:
    """Emit a Rich panel summarising a desktop tool call and its observation."""
    if not logger.isEnabledFor(logging.INFO):
        return

    from rich.panel import Panel
    from rich.text import Text

    body = Text()

    if not elements:
        body.append("(no interactive elements found)", style="dim italic")
    else:
        # Group elements by window, matching _format_a11y_tree layout.
        groups: dict[str, list[tuple[int, dict]]] = {}
        for i, el in enumerate(elements, 1):
            window = el.get("window") or "(desktop)"
            groups.setdefault(window, []).append((i, el))

        for window, items in groups.items():
            body.append("[%s]\n" % window, style="bold")
            for i, el in items:
                cx = el["x"] + el["w"] // 2
                cy = el["y"] + el["h"] // 2
                role = el.get("role") or "unknown"
                label = el.get("label") or ""
                states = el.get("states")
                state_str = " (%s)" % ", ".join(states) if states else ""

                body.append("  [%d] " % i, style="bold cyan")
                body.append("[%s] " % role, style="dim")
                body.append(label + state_str)
                body.append(" @ (%d, %d)\n" % (cx, cy), style="dim")

    title_parts = ["[bold cyan]%s[/bold cyan]" % tool_name]
    if args:
        title_parts.append("[dim]%s[/dim]" % args)
    title = "  ".join(title_parts)

    subtitle_parts = []
    if elapsed_ms > 0:
        subtitle_parts.append("[bold]%.0fms[/bold]" % elapsed_ms)
    subtitle_parts.append("%d elements" % len(elements))
    subtitle = "  ".join(subtitle_parts)

    _get_console().print(Panel(
        body,
        title=title,
        subtitle=subtitle,
        border_style="dim",
        expand=False,
    ))


async def _get_a11y_tree() -> list[dict]:
    """Get the accessibility tree from the container."""
    try:
        raw = await _run_desktop_cmd(
            "/usr/bin/python3.10 /opt/desktop/a11y_tree.py",
        )
        start = raw.find("[")
        if start == -1:
            return []
        return json.loads(raw[start:])
    except Exception:
        logger.debug("a11y tree unavailable", exc_info=True)
        return []


def _format_a11y_tree(elements: list[dict]) -> str:
    """Format a11y elements grouped by window for the agent."""
    if not elements:
        return ""

    # Group elements by window
    groups: dict[str, list[tuple[int, dict]]] = {}
    for i, el in enumerate(elements, 1):
        window = el.get("window") or "(desktop)"
        groups.setdefault(window, []).append((i, el))

    lines = ["INTERACTIVE ELEMENTS:"]
    for window, items in groups.items():
        lines.append("  [%s]" % window)
        for i, el in items:
            cx = el["x"] + el["w"] // 2
            cy = el["y"] + el["h"] // 2
            role = el.get("role") or "unknown"
            states = el.get("states")
            state_str = " (%s)" % ", ".join(states) if states else ""
            lines.append(
                "    [%d] [%s] %s%s — click at (%d, %d)"
                % (i, role, el["label"], state_str, cx, cy),
            )
    return "\n".join(lines)


async def _type_text(text: str) -> None:
    """Type text into the focused window.

    Uses xclip + Ctrl+V for text containing non-ASCII characters (emoji,
    Unicode) since xdotool cannot handle multi-byte sequences. Falls back
    to xdotool type for plain ASCII which works more reliably across
    terminal emulators that may not support Ctrl+V paste.
    """
    if text.isascii():
        for i in range(0, len(text), 50):
            chunk = text[i : i + 50]
            await _run_desktop_cmd(
                "xdotool type --clearmodifiers --delay 8 -- %s"
                % shlex.quote(chunk),
            )
    else:
        # Pipe through xclip then paste — handles any Unicode.
        await _run_desktop_cmd(
            "printf %%s %s | xclip -selection clipboard"
            % shlex.quote(text),
        )
        await _run_desktop_cmd("xdotool key --clearmodifiers ctrl+v")


async def _observe(tool_name: str = "observe", args: str = "") -> str:
    """Capture the accessibility tree as the desktop observation."""
    t0 = asyncio.get_event_loop().time()
    a11y_elements = await _get_a11y_tree()
    elapsed_ms = (asyncio.get_event_loop().time() - t0) * 1000
    observation = _format_a11y_tree(a11y_elements) or "(no interactive elements found)"
    _log_desktop_panel(
        tool_name, elements=a11y_elements, args=args, elapsed_ms=elapsed_ms,
    )
    return observation


async def read_screen() -> str:
    """Read the interactive elements currently visible on the desktop.

    Returns a numbered list of interactive elements (buttons, menus,
    text fields, etc.) with their roles, labels, and click coordinates
    from the accessibility tree.

    Returns:
        Numbered element list the agent can use to decide actions.
    """
    await ensure_desktop_running()
    return await _observe("read_screen")


_DESCRIBE_PROMPT = (
    "An AI agent needs to understand this desktop to decide its next action. "
    "For each window: title (active/inactive), one-sentence content summary. "
    "Then list any errors, dialogs, or prompts. "
    "Then list key text showing current state. "
    "Bullet points only. Maximum 300 words."
)


async def describe_screen() -> str:
    """Get a vision model description of what is visible on the desktop.

    Captures a screenshot and sends it to a vision model for a detailed
    text description. Use this when you need to understand visual context
    beyond the interactive element list from read_screen().

    Returns:
        Text description of the desktop from the vision model.
    """
    from llm import ProviderError
    from utility_models import vision_generate
    from settings import load_settings

    await ensure_desktop_running()
    t0 = asyncio.get_event_loop().time()

    try:
        screenshot_bytes = await capture_screenshot()
    except RuntimeError as exc:
        logger.exception("Failed to capture screenshot for describe_screen")
        return "Error: Failed to capture screenshot: %s" % exc

    encoded = base64.b64encode(screenshot_bytes).decode("ascii")

    try:
        answer = await vision_generate(_DESCRIBE_PROMPT, encoded)
    except ValueError as exc:
        return "Error: %s" % exc
    except ProviderError as exc:
        logger.exception("Vision model failed for describe_screen")
        return "Error: Vision model failed: %s" % exc

    if not answer:
        return "Error: Vision model returned an empty response."

    from tools._vision_logging import log_vision_panel

    settings = load_settings()
    elapsed_ms = (asyncio.get_event_loop().time() - t0) * 1000
    log_vision_panel(
        "describe_screen", settings.get("vision_model", ""),
        _DESCRIBE_PROMPT, answer, elapsed_ms,
    )

    return answer



async def mouse_click(x: int, y: int, button: str = "left") -> str:
    """Click at the specified coordinates on the desktop.

    Args:
        x: Horizontal pixel coordinate (0 = left edge).
        y: Vertical pixel coordinate (0 = top edge).
        button: Mouse button — "left", "right", or "middle".

    Returns:
        Observation of the desktop after clicking.
    """
    await ensure_desktop_running()
    button_map = {"left": "1", "middle": "2", "right": "3"}
    btn = button_map.get(button, "1")
    await _run_desktop_cmd(
        "xdotool mousemove --sync %d %d click %s" % (x, y, btn),
    )
    await asyncio.sleep(_SETTLE_DELAY_S)
    return await _observe("mouse_click", args="x=%d, y=%d, button=%s" % (x, y, button))


async def mouse_double_click(x: int, y: int) -> str:
    """Double-click at the specified coordinates on the desktop.

    Args:
        x: Horizontal pixel coordinate.
        y: Vertical pixel coordinate.

    Returns:
        Observation of the desktop after double-clicking.
    """
    await ensure_desktop_running()
    await _run_desktop_cmd(
        "xdotool mousemove --sync %d %d click --repeat 2 --delay 100 1"
        % (x, y),
    )
    await asyncio.sleep(_SETTLE_DELAY_S)
    return await _observe("mouse_double_click", args="x=%d, y=%d" % (x, y))


async def mouse_drag(x1: int, y1: int, x2: int, y2: int) -> str:
    """Drag from one point to another on the desktop.

    Args:
        x1: Start horizontal coordinate.
        y1: Start vertical coordinate.
        x2: End horizontal coordinate.
        y2: End vertical coordinate.

    Returns:
        Observation of the desktop after dragging.
    """
    await ensure_desktop_running()
    await _run_desktop_cmd(
        "xdotool mousemove --sync %d %d mousedown 1 "
        "mousemove --sync %d %d mouseup 1"
        % (x1, y1, x2, y2),
    )
    await asyncio.sleep(_SETTLE_DELAY_S)
    return await _observe(
        "mouse_drag", args="(%d,%d) -> (%d,%d)" % (x1, y1, x2, y2),
    )


async def keyboard_type(text: str) -> str:
    """Type text on the desktop.

    Uses xdotool keystroke simulation for ASCII text and clipboard paste
    (xclip + Ctrl+V) for Unicode/special characters.

    Args:
        text: The text to type.

    Returns:
        Observation of the desktop after typing.
    """
    await ensure_desktop_running()
    await _type_text(text)
    await asyncio.sleep(_SETTLE_DELAY_S)
    preview = text if len(text) <= 40 else text[:37] + "..."
    return await _observe("keyboard_type", args=repr(preview))


async def keyboard_press(key: str) -> str:
    """Press a key or key combination on the desktop.

    Args:
        key: Key name or combo, e.g. "Return", "ctrl+c", "alt+F4",
            "ctrl+shift+s". Uses xdotool key names.

    Returns:
        Observation of the desktop after pressing the key.
    """
    await ensure_desktop_running()
    await _run_desktop_cmd("xdotool key -- %s" % key)
    await asyncio.sleep(_SETTLE_DELAY_S)
    return await _observe("keyboard_press", args=key)


async def scroll(x: int, y: int, direction: str = "down", clicks: int = 3) -> str:
    """Scroll the mouse wheel at the specified position.

    Args:
        x: Horizontal pixel coordinate.
        y: Vertical pixel coordinate.
        direction: Scroll direction — "up" or "down".
        clicks: Number of scroll clicks.

    Returns:
        Observation of the desktop after scrolling.
    """
    await ensure_desktop_running()
    btn = "4" if direction == "up" else "5"
    await _run_desktop_cmd(
        "xdotool mousemove --sync %d %d click --repeat %d %s"
        % (x, y, clicks, btn),
    )
    await asyncio.sleep(_SETTLE_DELAY_S)
    return await _observe(
        "scroll", args="x=%d, y=%d, %s, clicks=%d" % (x, y, direction, clicks),
    )


async def desktop_shell(cmd: str) -> str:
    """Run a shell command on the desktop with DISPLAY set automatically.

    Use this for window management (wmctrl), launching GUI apps, or any
    command that needs access to the X11 display.

    Args:
        cmd: The shell command to execute on the desktop.

    Returns:
        Command output.
    """
    await ensure_desktop_running()
    output = await _run_desktop_cmd(cmd)
    return output.strip() or "ok"
