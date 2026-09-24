"""Vision-enabled browser tools.

Uses the configured LLM provider for visual question answering
(``inspect_page``) and the UI-TARS grounding server for action prediction
(``browser_visual_action``).
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import replace

from playwright.async_api import Error as PlaywrightError

from browser.core.document import Document
from browser.core.exceptions import BrowserToolError
from browser.core.formatting import format_rendered_document
from settings import load_settings
from tools.browser._tool_context import get_document
from tools.browser._tool_support import format_action_result
from tools.browser.events import emit_screenshot_after

logger = logging.getLogger(__name__)

_SCREENSHOT_TOOL_NAME = "inspect_page"
_VISUAL_ACTION_TOOL_NAME = "browser_visual_action"


async def inspect_page(
    prompt: str,
    *,
    mode: str = "full_page",
    ref: str | None = None,
    tab: str,
) -> str:
    """Inspect the current page visually and answer a question about it.  SLOW.

    Captures a screenshot and sends it to a vision model with your prompt.
    You never receive the image — only the model's text response.
    Be specific in your prompt to get structured, usable answers:
        GOOD: "List every item in the grid as row,col: value."
        GOOD: "What color is each cell? Format: position → color."
        GOOD: "Read the text shown in the image/canvas element."
        BAD:  "What does the page look like?" (too vague)

    Args:
        prompt: Specific question about what you see on the page.
        mode: ``"full_page"`` (default), ``"viewport"``, or ``"ref"``.
        ref: Required when ``mode="ref"`` — ref number of the
            element to capture.
        tab: Stable tab ID to inspect — the ID shown in the document
            header (e.g. ``tab="3"``).

    Returns:
        A text answer from the vision model (never an image).

    Raises:
        BrowserToolError: If capture or model generation fails.
    """
    t0 = asyncio.get_event_loop().time()

    clean_prompt = prompt.strip()
    if not clean_prompt:
        msg = "Prompt must be a non-empty string."
        raise BrowserToolError(msg, tool=_SCREENSHOT_TOOL_NAME)

    normalized_mode = mode.lower().strip()
    if normalized_mode not in {"full_page", "viewport", "ref"}:
        msg = "mode must be one of {'full_page', 'viewport', 'ref'}."
        raise BrowserToolError(msg, tool=_SCREENSHOT_TOOL_NAME)

    _browser, resolved_tab, document = await get_document(
        _SCREENSHOT_TOOL_NAME,
        tab=tab,
    )

    try:
        if normalized_mode == "ref":
            screenshot_bytes = await _ref_screenshot(document, ref)
        elif normalized_mode == "full_page":
            screenshot_bytes = await resolved_tab.screenshot(full_page=True)
        else:  # viewport
            screenshot_bytes = await resolved_tab.screenshot(full_page=False)
    except BrowserToolError:
        raise
    except PlaywrightError as exc:
        logger.exception("Failed to capture screenshot for page %s", resolved_tab.url)
        err_msg = f"Playwright error capturing screenshot: {exc}"
        raise BrowserToolError(err_msg, tool=_SCREENSHOT_TOOL_NAME) from exc
    except Exception as exc:  # pragma: no cover - unexpected Playwright failure
        logger.exception("Unexpected failure capturing screenshot for page %s", resolved_tab.url)
        err_msg = f"Unexpected failure capturing screenshot: {exc}"
        raise BrowserToolError(err_msg, tool=_SCREENSHOT_TOOL_NAME) from exc

    encoded_image = base64.b64encode(screenshot_bytes).decode("ascii")

    from agent_core.providers import ProviderError
    from providers import vision_generate

    try:
        answer = await vision_generate(clean_prompt, encoded_image)
    except ValueError as exc:
        raise BrowserToolError(str(exc), tool=_SCREENSHOT_TOOL_NAME) from exc
    except ProviderError as exc:
        logger.exception("Failed to generate answer for screenshot question")
        msg = "Failed to generate answer from screenshot."
        raise BrowserToolError(msg, tool=_SCREENSHOT_TOOL_NAME) from exc

    if not answer:
        msg = "Vision model did not return an answer."
        raise BrowserToolError(msg, tool=_SCREENSHOT_TOOL_NAME)

    from tools._vision_logging import log_vision_panel

    settings = load_settings()
    elapsed_ms = (asyncio.get_event_loop().time() - t0) * 1000
    log_vision_panel(
        "inspect_page",
        settings.get("vision_model", ""),
        clean_prompt,
        answer,
        elapsed_ms,
        image_source="%s (%s)" % (resolved_tab.url, normalized_mode),
    )

    return answer


@emit_screenshot_after
async def browser_visual_action(task: str, *, tab: str) -> str:
    """Ask a vision model to decide and execute the next GUI action.

    Only the current viewport is screenshotted — the target element must
    be visible on screen. Scroll it into view first if necessary.

    Supported actions (chosen automatically by the model): click,
    double-click, right-click, drag, type text, hotkey, scroll, and wait.

    Args:
        task: Natural-language description of what to do, e.g.
            ``"Click the Login button"``, ``"Drag the slider to the right"``,
            or ``"Type hello into the search box"``.
        tab: Stable tab ID to act on — the ID shown in the document
            header (e.g. ``tab="3"``).

    Returns:
        Updated rendered-document string after executing the action.

    Raises:
        BrowserToolError: If the page is inaccessible, the screenshot fails,
            the grounding server is unreachable, or the action fails.
    """
    from tools._grounding import run_grounding
    from tools.browser._visual_actions import execute_action

    clean_task = task.strip()
    if not clean_task:
        msg = "task must be a non-empty string."
        raise BrowserToolError(msg, tool=_VISUAL_ACTION_TOOL_NAME)

    browser, resolved_tab, document = await get_document(
        _VISUAL_ACTION_TOOL_NAME,
        tab=tab,
    )

    # Capture viewport screenshot.
    try:
        screenshot_bytes = await resolved_tab.screenshot(full_page=False)
    except PlaywrightError as exc:
        logger.exception(
            "Failed to capture screenshot for visual action on %s",
            resolved_tab.url,
        )
        msg = "Failed to capture screenshot for visual action."
        raise BrowserToolError(msg, tool=_VISUAL_ACTION_TOOL_NAME) from exc

    # Send to grounding server.
    try:
        response = await run_grounding(
            screenshot_bytes,
            clean_task,
            screenshot_filename="browser_visual_action.png",
        )
    except RuntimeError as exc:
        logger.exception("Grounding request failed for %r", clean_task)
        msg = "Grounding request failed: %s" % exc
        raise BrowserToolError(msg, tool=_VISUAL_ACTION_TOOL_NAME) from exc

    logger.info(
        "Visual action: %s → %s (thought: %s)",
        clean_task,
        response.action_type,
        response.thought,
    )

    # Handle finished — return the rendered document with a note.
    if response.action_type == "finished":
        finished_content = response.raw.get("finished_content", "")
        rendered = await resolved_tab.render_document(settle=False)
        content = rendered.content
        if finished_content:
            content += "\n\n--- Vision model says task is finished: %s ---" % finished_content
        return format_rendered_document(
            replace(rendered, content=content),
            tab_id=resolved_tab.id,
        )

    # Coordinate the action so the resulting document is settled and rendered.
    try:
        result = await browser.coordinate_action(
            lambda: execute_action(response, document),
            source_tab=resolved_tab,
        )
        return await format_action_result(
            result,
            tool_name=_VISUAL_ACTION_TOOL_NAME,
        )
    except BrowserToolError:
        raise
    except PlaywrightError as exc:
        logger.exception("Visual action execution failed for %r", clean_task)
        msg = "Visual action execution failed: %s" % exc
        raise BrowserToolError(msg, tool=_VISUAL_ACTION_TOOL_NAME) from exc


async def _ref_screenshot(document: Document, ref: str | None) -> bytes:
    if ref is None:
        msg = "ref cannot be None when mode='ref'."
        raise BrowserToolError(msg, tool=_SCREENSHOT_TOOL_NAME)
    clean_ref = ref.strip()
    if not clean_ref:
        msg = "ref must be non-empty when mode='ref'."
        raise BrowserToolError(msg, tool=_SCREENSHOT_TOOL_NAME)

    resolution = await document.resolve_ref(clean_ref, tool_name=_SCREENSHOT_TOOL_NAME)
    return await document.screenshot(resolution)


__all__ = [
    "browser_visual_action",
    "inspect_page",
]
