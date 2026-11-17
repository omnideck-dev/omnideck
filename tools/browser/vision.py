"""Vision-enabled browser tools.

Uses the configured LLM provider for visual question answering
(``inspect_page``).
"""

from __future__ import annotations

import asyncio
import base64
import logging

from playwright.async_api import Error as PlaywrightError

from browser.core.document import Document
from browser.core.exceptions import BrowserToolError
from settings import load_settings
from tools.browser._tool_context import get_document

logger = logging.getLogger(__name__)

_SCREENSHOT_TOOL_NAME = "inspect_page"


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
        msg = f"Failed to generate answer from screenshot: {exc}"
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
    "inspect_page",
]
