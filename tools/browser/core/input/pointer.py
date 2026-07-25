"""Human-like pointer input for browser documents."""

from __future__ import annotations

import asyncio
import logging
import math
import random
import weakref

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page

from tools.browser.core.exceptions import BrowserToolError
from tools.browser.core.input._shared import _get_human_config, _sleep_ms

logger = logging.getLogger(__name__)


# A user-visible, in-page cursor overlay that makes automated pointer movement
# easy to follow in screenshots and browser-control views. This is strictly a
# cosmetic DOM element that does not affect the real OS pointer. Failures are
# intentionally ignored (CSP, sandboxed pages, or other restrictions) so
# automation continues to function even when the overlay cannot be installed.
_CURSOR_OVERLAY_SCRIPT = """
({ points, durationMs }) => {
    const controllerKey = Symbol.for('omnideck.browser.cursor');
    let controller = window[controllerKey];

    if (!controller) {
        controller = {
            ring: null,
            dot: null,
            animationFrame: null,

            install() {
                if (!this.ring || !this.ring.isConnected) {
                    this.ring = document.getElementById('__llm_cursor_ring__');
                    if (!this.ring) {
                        this.ring = document.createElement('div');
                        this.ring.id = '__llm_cursor_ring__';
                        this.ring.style.cssText = `
                            position:fixed;
                            width:96px;
                            height:96px;
                            border:8px solid #fff;
                            border-radius:50%;
                            background:rgba(0,0,0,0.35);
                            box-shadow:0 0 18px rgba(0,0,0,0.45);
                            pointer-events:none;
                            z-index:2147483647;
                            left:-9999px;
                            top:-9999px;
                            transform:translate(-50%,-50%);
                        `;
                        (document.body || document.documentElement).appendChild(this.ring);
                    }
                }

                if (!this.dot || !this.dot.isConnected) {
                    this.dot = document.getElementById('__llm_cursor_dot__');
                    if (!this.dot) {
                        this.dot = document.createElement('div');
                        this.dot.id = '__llm_cursor_dot__';
                        this.dot.style.cssText = `
                            position:fixed;
                            width:16px;
                            height:16px;
                            border-radius:50%;
                            background:rgba(255,60,60,0.95);
                            box-shadow:0 0 8px rgba(255,60,60,0.9);
                            pointer-events:none;
                            z-index:2147483648;
                            left:-9999px;
                            top:-9999px;
                            transform:translate(-50%,-50%);
                        `;
                        (document.body || document.documentElement).appendChild(this.dot);
                    }
                }
            },

            setPosition(x, y) {
                if (!this.ring || !this.dot) return;
                this.ring.style.left = x + 'px';
                this.ring.style.top = y + 'px';
                this.dot.style.left = x + 'px';
                this.dot.style.top = y + 'px';
            },

            animate(path, totalDurationMs) {
                this.install();
                if (!Array.isArray(path) || path.length === 0) return;

                if (this.animationFrame !== null) {
                    cancelAnimationFrame(this.animationFrame);
                }

                const finalPoint = path[path.length - 1];
                this.setPosition(path[0][0], path[0][1]);
                if (totalDurationMs <= 0 || path.length === 1) {
                    this.setPosition(finalPoint[0], finalPoint[1]);
                    this.animationFrame = null;
                    return;
                }

                const startedAt = performance.now();
                const paint = (now) => {
                    const progress = Math.min(1, (now - startedAt) / totalDurationMs);
                    const position = progress * (path.length - 1);
                    const lowerIndex = Math.floor(position);
                    const upperIndex = Math.min(path.length - 1, lowerIndex + 1);
                    const fraction = position - lowerIndex;
                    const lower = path[lowerIndex];
                    const upper = path[upperIndex];
                    const x = lower[0] + (upper[0] - lower[0]) * fraction;
                    const y = lower[1] + (upper[1] - lower[1]) * fraction;
                    this.setPosition(x, y);

                    if (progress < 1) {
                        this.animationFrame = requestAnimationFrame(paint);
                    } else {
                        this.animationFrame = null;
                    }
                };
                this.animationFrame = requestAnimationFrame(paint);
            },
        };
        window[controllerKey] = controller;
    }

    controller.animate(points, durationMs);
}
"""


_POINTER_POSITIONS: weakref.WeakKeyDictionary[Page, tuple[float, float]] = weakref.WeakKeyDictionary()


def _last_pointer_position(page: Page, *, fallback: tuple[float, float]) -> tuple[float, float]:
    """Return this page's last trusted pointer destination."""
    try:
        return _POINTER_POSITIONS.get(page, fallback)
    except TypeError:
        return fallback


def _remember_pointer_position(page: Page, *, x: float, y: float) -> None:
    """Remember a trusted pointer destination without retaining closed pages."""
    try:
        _POINTER_POSITIONS[page] = (x, y)
    except TypeError:
        pass


def _bezier_point(
    t: float,
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
) -> tuple[float, float]:
    """Evaluate a cubic Bezier curve at parameter t (0..1)."""
    u = 1 - t
    x = u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0]
    y = u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]
    return x, y


def _ease_in_out(t: float) -> float:
    """Sinusoidal ease-in-out: slow start, fast middle, slow end."""
    return (1 - math.cos(t * math.pi)) / 2


def _build_trajectory(
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
) -> list[tuple[float, float]]:
    """Build a natural-looking mouse trajectory using a cubic Bezier curve.

    The trajectory uses random control points offset from the straight line,
    an ease-in-out velocity profile, and per-step micro-jitter to simulate
    hand tremor.  Step count scales with distance (~50px per step).
    """
    dx = end_x - start_x
    dy = end_y - start_y
    dist = math.hypot(dx, dy)

    # Calculate step count from distance — ~50px per step, minimum 2
    adaptive_steps = max(2, int(dist / 50))

    # Generate two random control points offset perpendicular to the line.
    # Offset magnitude scales with distance but caps to avoid wild curves.
    max_offset = min(dist * 0.3, 80)
    offset1 = random.uniform(-max_offset, max_offset)
    offset2 = random.uniform(-max_offset, max_offset)

    # Perpendicular direction (rotate 90 degrees)
    if dist > 0:
        perp_x = -dy / dist
        perp_y = dx / dist
    else:
        perp_x, perp_y = 0.0, 1.0

    # Control points at ~1/3 and ~2/3 along the line, offset perpendicular
    cp1 = (
        start_x + dx * 0.3 + perp_x * offset1,
        start_y + dy * 0.3 + perp_y * offset1,
    )
    cp2 = (
        start_x + dx * 0.7 + perp_x * offset2,
        start_y + dy * 0.7 + perp_y * offset2,
    )

    p0 = (start_x, start_y)
    p3 = (end_x, end_y)

    points: list[tuple[float, float]] = []
    for i in range(1, adaptive_steps + 1):
        # Ease-in-out: remap linear t to slow-fast-slow progression
        t_linear = i / adaptive_steps
        t_eased = _ease_in_out(t_linear)

        bx, by = _bezier_point(t_eased, p0, cp1, cp2, p3)

        # Add micro-jitter (±1.5px) to simulate hand tremor, except on the
        # final step which must land precisely on the target.
        if i < adaptive_steps:
            jitter = 1.5
            bx += random.uniform(-jitter, jitter)
            by += random.uniform(-jitter, jitter)

        points.append((bx, by))

    return points


async def _mouse_move_with_fake_cursor(page: Page, *, x: float, y: float) -> None:
    """Move the Playwright mouse along a natural Bezier trajectory.

    Uses a cubic Bezier curve with random control points, an ease-in-out
    velocity profile, and per-step micro-jitter to produce human-like
    mouse movement. Also updates the in-page fake cursor overlay.
    """
    start_x, start_y = _last_pointer_position(page, fallback=(x, y))
    trajectory = _build_trajectory(start_x, start_y, x, y)
    cfg = _get_human_config()
    duration_ms = random.randint(
        cfg.move_duration_min_ms,
        cfg.move_duration_max_ms,
    )

    try:
        await page.evaluate(
            _CURSOR_OVERLAY_SCRIPT,
            {"points": trajectory, "durationMs": duration_ms},
        )
    except PlaywrightError as exc:
        logger.warning(
            "Failed to animate fake cursor on page %s; continuing with trusted pointer movement. Error: %s",
            getattr(page, "url", "<unknown>"),
            exc,
        )

    intervals = max(1, len(trajectory) - 1)
    step_delay_seconds = duration_ms / intervals / 1000
    for index, (xi, yi) in enumerate(trajectory):
        await page.mouse.move(xi, yi, steps=1)
        if index < len(trajectory) - 1 and step_delay_seconds > 0:
            await asyncio.sleep(step_delay_seconds)

    _remember_pointer_position(page, x=x, y=y)


async def human_click(page: Page, locator: Locator) -> None:
    """Click an element with human-like pointer movement and timing.

    Args:
        page: Owning page that receives physical input.
        locator: Locator identifying the element to click.

    Raises:
        BrowserToolError: If the locator cannot be resolved or the page lacks a mouse.
    """
    cfg = _get_human_config()
    if hasattr(locator, "scroll_into_view_if_needed"):
        try:
            await locator.scroll_into_view_if_needed(timeout=5000)
        except PlaywrightError as exc:  # pragma: no cover - defensive
            logger.debug("scroll_into_view_if_needed failed prior to click: %s", exc)
    handle = await locator.element_handle(timeout=5000)
    if handle is None:
        raise BrowserToolError("Unable to resolve element handle", tool="click")
    # A DOM locator supplies the element, while the owning tab supplies the
    # physical pointer. A detached element has no shared render coordinates,
    # so it cannot be driven through the tab's mouse.
    frame = await handle.owner_frame()
    if frame is None:
        raise BrowserToolError(
            "Element is not attached to a frame/page; cannot perform mouse-based click",
            tool="click",
        )

    box = await handle.bounding_box()
    if box is None or box.get("width", 0) < 4 or box.get("height", 0) < 4:
        label_handle = await handle.evaluate_handle("(el) => el.labels?.[0] ?? null")
        try:
            label_element = label_handle.as_element()
            if label_element is not None:
                label_box = await label_element.bounding_box()
                if label_box and label_box.get("width", 0) >= 4 and label_box.get("height", 0) >= 4:
                    box = label_box
        finally:
            await label_handle.dispose()

    if box is None or box.get("width", 0) <= 0 or box.get("height", 0) <= 0:
        # No usable bounding box; the caller should ensure the ref points to a visible element.
        raise BrowserToolError("Element has no bounding box to click", tool="click")

    if not hasattr(page, "mouse") or page.mouse is None:
        raise BrowserToolError("Provided page has no mouse available", tool="click")

    target_x = box["x"] + box["width"] / 2
    target_y = box["y"] + box["height"] / 2

    # Add small random offset within the element (~10% of dimensions)
    jitter_x = box["width"] * 0.1
    jitter_y = box["height"] * 0.1
    target_x += random.uniform(-jitter_x, jitter_x)
    target_y += random.uniform(-jitter_y, jitter_y)

    mouse = page.mouse
    await _mouse_move_with_fake_cursor(page, x=target_x, y=target_y)
    await _sleep_ms(random.randint(cfg.hover_min_ms, cfg.hover_max_ms))
    await mouse.down()
    await _sleep_ms(random.randint(cfg.click_hold_min_ms, cfg.click_hold_max_ms))
    await mouse.up()


async def human_press_and_hold(
    page: Page,
    locator: Locator,
    duration_ms: int = 3000,
) -> None:
    """Press and hold an element for a specified duration.

    Performs the same human-like positioning as ``human_click`` but holds the
    mouse button down for ``duration_ms`` milliseconds before releasing.

    Args:
        page: Owning page that receives physical input.
        locator: Locator identifying the element to press and hold.
        duration_ms: How long to hold the mouse button down in milliseconds.

    Raises:
        BrowserToolError: If the locator cannot be resolved or the page lacks a mouse.
    """
    cfg = _get_human_config()
    if hasattr(locator, "scroll_into_view_if_needed"):
        try:
            await locator.scroll_into_view_if_needed(timeout=5000)
        except PlaywrightError as exc:  # pragma: no cover - defensive
            logger.debug("scroll_into_view_if_needed failed prior to press_and_hold: %s", exc)
    handle = await locator.element_handle(timeout=5000)
    if handle is None:
        raise BrowserToolError("Unable to resolve element handle", tool="press_and_hold")

    frame = await handle.owner_frame()
    if frame is None:
        raise BrowserToolError(
            "Element is not attached to a frame/page; cannot perform press_and_hold",
            tool="press_and_hold",
        )

    box = await handle.bounding_box()
    if box is None or box.get("width", 0) < 4 or box.get("height", 0) < 4:
        label_handle = await handle.evaluate_handle("(el) => el.labels?.[0] ?? null")
        try:
            label_element = label_handle.as_element()
            if label_element is not None:
                label_box = await label_element.bounding_box()
                if label_box and label_box.get("width", 0) >= 4 and label_box.get("height", 0) >= 4:
                    box = label_box
        finally:
            await label_handle.dispose()

    if box is None or box.get("width", 0) <= 0 or box.get("height", 0) <= 0:
        raise BrowserToolError("Element has no bounding box to press", tool="press_and_hold")

    if not hasattr(page, "mouse") or page.mouse is None:
        raise BrowserToolError("Provided page has no mouse available", tool="press_and_hold")

    target_x = box["x"] + box["width"] / 2
    target_y = box["y"] + box["height"] / 2

    jitter_x = box["width"] * 0.1
    jitter_y = box["height"] * 0.1
    target_x += random.uniform(-jitter_x, jitter_x)
    target_y += random.uniform(-jitter_y, jitter_y)

    mouse = page.mouse
    await _mouse_move_with_fake_cursor(page, x=target_x, y=target_y)
    await _sleep_ms(random.randint(cfg.hover_min_ms, cfg.hover_max_ms))
    await mouse.down()

    # Hold for the requested duration.
    await _sleep_ms(max(0, duration_ms))

    await mouse.up()


async def human_drag(
    page: Page,
    source_locator: Locator,
    *,
    target_locator: Locator,
) -> None:
    """Drag from ``source_locator`` to ``target_locator``.

    Args:
        page: Owning page that receives physical input.
        source_locator: Locator identifying the element where the drag should begin.
        target_locator: Locator identifying the destination element.

    Raises:
        BrowserToolError: On invalid inputs, detached elements, missing mouse APIs,
            or when bounding boxes cannot be computed.
    """

    cfg = _get_human_config()

    source_handle = await source_locator.element_handle(timeout=5000)
    if source_handle is None:
        raise BrowserToolError("Unable to resolve source element handle", tool="drag")

    source_frame = await source_handle.owner_frame()
    if source_frame is None:
        raise BrowserToolError(
            "Source element is not attached to a frame/page; cannot perform drag",
            tool="drag",
        )

    source_box = await source_handle.bounding_box()
    if source_box is None or source_box.get("width", 0) < 4 or source_box.get("height", 0) < 4:
        label_handle = None
        try:
            label_handle = await source_handle.evaluate_handle("(el) => el.labels?.[0] ?? null")
        except PlaywrightError as exc:
            logger.warning(
                "Failed to evaluate source label handle; using element's own bounding box if available. Error: %s",
                exc,
            )
            label_handle = None
        if label_handle is not None:
            try:
                label_element = label_handle.as_element()
                if label_element is not None:
                    label_box = await label_element.bounding_box()
                    if label_box and label_box.get("width", 0) >= 4 and label_box.get("height", 0) >= 4:
                        source_box = label_box
            finally:
                try:
                    await label_handle.dispose()
                except PlaywrightError as exc:
                    logger.warning("Failed to dispose source label handle; continuing. Error: %s", exc)

    if source_box is None or source_box.get("width", 0) <= 0 or source_box.get("height", 0) <= 0:
        raise BrowserToolError("Source element has no bounding box to drag", tool="drag")

    if not hasattr(page, "mouse") or page.mouse is None:
        raise BrowserToolError("Provided page has no mouse available", tool="drag")

    start_x = source_box["x"] + source_box["width"] / 2
    start_y = source_box["y"] + source_box["height"] / 2

    jitter_x = source_box["width"] * 0.1
    jitter_y = source_box["height"] * 0.1
    start_x += random.uniform(-jitter_x, jitter_x)
    start_y += random.uniform(-jitter_y, jitter_y)

    target_handle = await target_locator.element_handle(timeout=5000)
    if target_handle is None:
        raise BrowserToolError("Unable to resolve target element handle", tool="drag")

    target_frame = await target_handle.owner_frame()
    if target_frame is None:
        raise BrowserToolError(
            "Target element is not attached to a frame/page; cannot perform drag",
            tool="drag",
        )

    target_box = await target_handle.bounding_box()
    if target_box is None or target_box.get("width", 0) < 4 or target_box.get("height", 0) < 4:
        label_handle = None
        try:
            label_handle = await target_handle.evaluate_handle("(el) => el.labels?.[0] ?? null")
        except PlaywrightError as exc:
            logger.warning(
                "Failed to evaluate target label handle; using element's own bounding box if available. Error: %s",
                exc,
            )
            label_handle = None
        if label_handle is not None:
            try:
                label_element = label_handle.as_element()
                if label_element is not None:
                    label_box = await label_element.bounding_box()
                    if label_box and label_box.get("width", 0) >= 4 and label_box.get("height", 0) >= 4:
                        target_box = label_box
            finally:
                try:
                    await label_handle.dispose()
                except PlaywrightError as exc:
                    logger.warning("Failed to dispose target label handle; continuing. Error: %s", exc)

    if target_box is None or target_box.get("width", 0) <= 0 or target_box.get("height", 0) <= 0:
        raise BrowserToolError("Target element has no bounding box to drag", tool="drag")

    dest_x = target_box["x"] + target_box["width"] / 2
    dest_y = target_box["y"] + target_box["height"] / 2

    jitter_x = target_box["width"] * 0.1
    jitter_y = target_box["height"] * 0.1
    dest_x += random.uniform(-jitter_x, jitter_x)
    dest_y += random.uniform(-jitter_y, jitter_y)

    mouse = page.mouse

    # Move to drag start, press, glide to destination, then release.
    await _mouse_move_with_fake_cursor(page, x=start_x, y=start_y)
    await _sleep_ms(random.randint(cfg.hover_min_ms, cfg.hover_max_ms))
    await mouse.down()
    await _sleep_ms(random.randint(cfg.click_hold_min_ms, cfg.click_hold_max_ms))
    await _mouse_move_with_fake_cursor(page, x=dest_x, y=dest_y)
    await _sleep_ms(random.randint(cfg.hover_min_ms, cfg.hover_max_ms))
    await mouse.up()


def _random_point_in_bbox(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> tuple[float, float]:
    """Pick a random point inside a bounding box, biased toward the center.

    Uses a truncated gaussian (clamped to bbox) so clicks cluster naturally
    near the center but still vary across the full element area.
    """
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    # Sigma = 1/4 of dimension so ~95% of samples fall within the bbox
    sx = max((x2 - x1) / 4.0, 0.5)
    sy = max((y2 - y1) / 4.0, 0.5)
    px = max(x1, min(x2, random.gauss(cx, sx)))
    py = max(y1, min(y2, random.gauss(cy, sy)))
    return px, py


async def human_click_at(
    page: Page,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> None:
    """Perform a human-like click at a random point inside a bounding box.

    Bypasses locator/bounding-box resolution entirely, allowing clicks on
    elements for which no rendered-document ref is available (shadow DOM, iframes,
    dynamically injected content).

    Args:
        page: Owning page that receives physical input.
        x1: Left edge of the bounding box (CSS pixels).
        y1: Top edge of the bounding box (CSS pixels).
        x2: Right edge of the bounding box (CSS pixels).
        y2: Bottom edge of the bounding box (CSS pixels).

    Raises:
        BrowserToolError: If coordinates are non-finite or the page lacks a mouse.
    """
    coords = (x1, y1, x2, y2)
    if not all(math.isfinite(c) for c in coords):
        raise BrowserToolError("Coordinates must be finite numbers", tool="click_at")

    cfg = _get_human_config()

    if not hasattr(page, "mouse") or page.mouse is None:
        raise BrowserToolError("Provided page has no mouse available", tool="click_at")

    target_x, target_y = _random_point_in_bbox(x1, y1, x2, y2)

    mouse = page.mouse
    await _mouse_move_with_fake_cursor(page, x=target_x, y=target_y)
    await _sleep_ms(random.randint(cfg.hover_min_ms, cfg.hover_max_ms))
    await mouse.down()
    await _sleep_ms(random.randint(cfg.click_hold_min_ms, cfg.click_hold_max_ms))
    await mouse.up()


async def human_press_and_hold_at(
    page: Page,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    duration_ms: int = 3000,
) -> None:
    """Press and hold at a random point inside a bounding box for a duration.

    Bypasses locator/bounding-box resolution entirely.

    Args:
        page: Owning page that receives physical input.
        x1: Left edge of the bounding box (CSS pixels).
        y1: Top edge of the bounding box (CSS pixels).
        x2: Right edge of the bounding box (CSS pixels).
        y2: Bottom edge of the bounding box (CSS pixels).
        duration_ms: How long to hold the mouse button down in milliseconds.

    Raises:
        BrowserToolError: If coordinates are non-finite or the page lacks a mouse.
    """
    coords = (x1, y1, x2, y2)
    if not all(math.isfinite(c) for c in coords):
        raise BrowserToolError("Coordinates must be finite numbers", tool="press_and_hold_at")

    cfg = _get_human_config()

    if not hasattr(page, "mouse") or page.mouse is None:
        raise BrowserToolError("Provided page has no mouse available", tool="press_and_hold_at")

    target_x, target_y = _random_point_in_bbox(x1, y1, x2, y2)

    mouse = page.mouse
    await _mouse_move_with_fake_cursor(page, x=target_x, y=target_y)
    await _sleep_ms(random.randint(cfg.hover_min_ms, cfg.hover_max_ms))
    await mouse.down()

    # Hold for the requested duration.
    await _sleep_ms(max(0, duration_ms))

    await mouse.up()


async def human_double_click_at(
    page: Page,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> None:
    """Perform a human-like double-click at a random point inside a bounding box.

    Args:
        page: Owning page that receives physical input.
        x1: Left edge of the bounding box (CSS pixels).
        y1: Top edge of the bounding box (CSS pixels).
        x2: Right edge of the bounding box (CSS pixels).
        y2: Bottom edge of the bounding box (CSS pixels).

    Raises:
        BrowserToolError: If coordinates are non-finite or the page lacks a mouse.
    """
    coords = (x1, y1, x2, y2)
    if not all(math.isfinite(c) for c in coords):
        raise BrowserToolError("Coordinates must be finite numbers", tool="double_click_at")

    cfg = _get_human_config()

    if not hasattr(page, "mouse") or page.mouse is None:
        raise BrowserToolError("Provided page has no mouse available", tool="double_click_at")

    target_x, target_y = _random_point_in_bbox(x1, y1, x2, y2)

    mouse = page.mouse
    await _mouse_move_with_fake_cursor(page, x=target_x, y=target_y)
    await _sleep_ms(random.randint(cfg.hover_min_ms, cfg.hover_max_ms))

    # Use Playwright's native dblclick to guarantee the browser fires a
    # 'dblclick' DOM event. Manual down/up pairs can miss the timing
    # window depending on browser configuration.
    await mouse.dblclick(target_x, target_y)


async def human_right_click_at(
    page: Page,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> None:
    """Perform a human-like right-click at a random point inside a bounding box.

    Args:
        page: Owning page that receives physical input.
        x1: Left edge of the bounding box (CSS pixels).
        y1: Top edge of the bounding box (CSS pixels).
        x2: Right edge of the bounding box (CSS pixels).
        y2: Bottom edge of the bounding box (CSS pixels).

    Raises:
        BrowserToolError: If coordinates are non-finite or the page lacks a mouse.
    """
    coords = (x1, y1, x2, y2)
    if not all(math.isfinite(c) for c in coords):
        raise BrowserToolError("Coordinates must be finite numbers", tool="right_click_at")

    cfg = _get_human_config()

    if not hasattr(page, "mouse") or page.mouse is None:
        raise BrowserToolError("Provided page has no mouse available", tool="right_click_at")

    target_x, target_y = _random_point_in_bbox(x1, y1, x2, y2)

    mouse = page.mouse
    await _mouse_move_with_fake_cursor(page, x=target_x, y=target_y)
    await _sleep_ms(random.randint(cfg.hover_min_ms, cfg.hover_max_ms))
    await mouse.down(button="right")
    await _sleep_ms(random.randint(cfg.click_hold_min_ms, cfg.click_hold_max_ms))
    await mouse.up(button="right")


async def human_drag_at(
    page: Page,
    sx1: float,
    sy1: float,
    sx2: float,
    sy2: float,
    dx1: float,
    dy1: float,
    dx2: float,
    dy2: float,
) -> None:
    """Drag from a random point in the source bbox to a random point in the dest bbox.

    Args:
        page: Owning page that receives physical input.
        sx1: Source bounding box left edge (CSS pixels).
        sy1: Source bounding box top edge (CSS pixels).
        sx2: Source bounding box right edge (CSS pixels).
        sy2: Source bounding box bottom edge (CSS pixels).
        dx1: Destination bounding box left edge (CSS pixels).
        dy1: Destination bounding box top edge (CSS pixels).
        dx2: Destination bounding box right edge (CSS pixels).
        dy2: Destination bounding box bottom edge (CSS pixels).

    Raises:
        BrowserToolError: If coordinates are non-finite or the page lacks a mouse.
    """
    all_coords = (sx1, sy1, sx2, sy2, dx1, dy1, dx2, dy2)
    if not all(math.isfinite(c) for c in all_coords):
        raise BrowserToolError("Coordinates must be finite numbers", tool="drag_at")

    cfg = _get_human_config()

    if not hasattr(page, "mouse") or page.mouse is None:
        raise BrowserToolError("Provided page has no mouse available", tool="drag_at")

    start_x, start_y = _random_point_in_bbox(sx1, sy1, sx2, sy2)
    dest_x, dest_y = _random_point_in_bbox(dx1, dy1, dx2, dy2)

    mouse = page.mouse

    # Move to drag start, press, glide to destination, then release.
    await _mouse_move_with_fake_cursor(page, x=start_x, y=start_y)
    await _sleep_ms(random.randint(cfg.hover_min_ms, cfg.hover_max_ms))
    await mouse.down()
    await _sleep_ms(random.randint(cfg.click_hold_min_ms, cfg.click_hold_max_ms))
    await _mouse_move_with_fake_cursor(page, x=dest_x, y=dest_y)
    await _sleep_ms(random.randint(cfg.hover_min_ms, cfg.hover_max_ms))
    await mouse.up()


__all__ = [
    "human_click",
    "human_click_at",
    "human_double_click_at",
    "human_drag",
    "human_drag_at",
    "human_press_and_hold",
    "human_press_and_hold_at",
    "human_right_click_at",
]
