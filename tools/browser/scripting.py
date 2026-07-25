"""Agent tool for advanced JavaScript execution in a tab."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from tools.browser._tool_context import get_document
from tools.browser.core.formatting import format_javascript_result
from tools.browser.events import emit_screenshot

logger = logging.getLogger(__name__)
_console = Console(stderr=True)

_CODE_PREVIEW_LEN = 120

# Code that Playwright's evaluate() accepts as-is: a function
# (``() => ...`` / ``function`` / ``async``) or a parenthesized expression.
# Anything else that uses a top-level ``return`` must be wrapped in a function.
_FUNCTION_OR_PAREN_START = re.compile(r"^\s*(async\s+)?(function\b|\(|[A-Za-z_$][\w$]*\s*=>)")


def _as_evaluatable(code: str) -> str:
    """Make agent-supplied JS runnable by Playwright's ``evaluate``.

    ``evaluate`` accepts a function or a bare expression but rejects a top-level
    ``return`` ("Illegal return statement"). Wrap statement-style code that uses
    ``return`` in an arrow function so the documented ``return`` form works;
    pass functions and plain expressions through unchanged.
    """
    stripped = code.strip()
    if _FUNCTION_OR_PAREN_START.match(stripped):
        return code
    if re.search(r"\breturn\b", stripped):
        return f"() => {{ {code} }}"
    return code


async def execute_javascript(
    code: str,
    timeout_ms: int = 10000,
    *,
    tab: str,
) -> str:
    """Execute JavaScript in the page context.  Advanced — prefer structured tools.

    Only use when ``click()``, ``fill_field()``, ``browse_page()`` cannot
    accomplish the task.  Useful for removing popups, extracting custom data
    structures, or checking page state.

    ``console.log()`` output is captured in the ``console_output`` field.
    Return a JSON-serializable value for structured data — a bare
    ``return expr;``, a plain expression (``document.title``), or a function
    (``() => {...}``) all work.

    Args:
        code: JavaScript to run — an expression, statements using ``return``,
            or a ``() => {...}`` function.
        timeout_ms: Maximum wait time in milliseconds (default 10000).
        tab: Stable tab ID to act on — the ID shown in the document
            header (e.g. ``tab="3"``).

    Returns:
        Formatted string with success/error status, result, and console output.

    Raises:
        BrowserToolError: If browser is not initialized or page is not available.
    """
    _browser, resolved_tab, document = await get_document(
        "execute_javascript",
        tab=tab,
    )

    async with resolved_tab.capture_console() as console_lines:
        code_preview = code.strip().replace("\n", " ")
        if len(code_preview) > _CODE_PREVIEW_LEN:
            code_preview = code_preview[:_CODE_PREVIEW_LEN] + "…"

        t0 = time.perf_counter()
        try:
            result_value = await asyncio.wait_for(
                document.evaluate(_as_evaluatable(code)),
                timeout=timeout_ms / 1000,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000

            await emit_screenshot(resolved_tab)

            _print_js_panel(
                success=True,
                code_preview=code_preview,
                url=resolved_tab.url,
                elapsed_ms=elapsed_ms,
                result=result_value,
                console_lines=console_lines,
            )

            return format_javascript_result(
                success=True,
                result=result_value,
                console_output=console_lines or None,
            )

        except TimeoutError:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            error_msg = f"JavaScript execution timed out after {timeout_ms}ms"
            _print_js_panel(
                success=False,
                code_preview=code_preview,
                url=resolved_tab.url,
                elapsed_ms=elapsed_ms,
                error=error_msg,
                console_lines=console_lines,
            )
            return format_javascript_result(
                success=False,
                console_output=console_lines or None,
                error=error_msg,
            )

        except PlaywrightTimeoutError as e:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            error_msg = f"JavaScript execution timed out after {timeout_ms}ms: {e}"
            _print_js_panel(
                success=False,
                code_preview=code_preview,
                url=resolved_tab.url,
                elapsed_ms=elapsed_ms,
                error=error_msg,
                console_lines=console_lines,
            )
            return format_javascript_result(
                success=False,
                console_output=console_lines or None,
                error=error_msg,
            )

        except PlaywrightError as e:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            error_msg = f"JavaScript execution failed: {e}"
            _print_js_panel(
                success=False,
                code_preview=code_preview,
                url=resolved_tab.url,
                elapsed_ms=elapsed_ms,
                error=error_msg,
                console_lines=console_lines,
            )
            return format_javascript_result(
                success=False,
                console_output=console_lines or None,
                error=error_msg,
            )

        except Exception as e:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            error_msg = f"Unexpected error during JavaScript execution: {e}"
            logger.exception("Unexpected error executing JavaScript")
            _print_js_panel(
                success=False,
                code_preview=code_preview,
                url=resolved_tab.url,
                elapsed_ms=elapsed_ms,
                error=error_msg,
                console_lines=console_lines,
            )
            return format_javascript_result(
                success=False,
                console_output=console_lines or None,
                error=error_msg,
            )


def _print_js_panel(
    *,
    success: bool,
    code_preview: str,
    url: str,
    elapsed_ms: float,
    result: Any = None,
    error: str | None = None,
    console_lines: list[str] | None = None,
) -> None:
    """Print a Rich panel summarizing a JavaScript execution."""
    status = "[bold green]OK[/bold green]" if success else "[bold red]FAIL[/bold red]"
    title = f"[bold yellow]execute_javascript[/bold yellow]  {status}"

    body = Text()
    body.append(code_preview, style="dim")

    if success and result is not None:
        result_str = str(result)
        if len(result_str) > 200:
            result_str = result_str[:200] + "…"
        body.append("\nresult: ", style="bold")
        body.append(result_str, style="green")
    elif error:
        body.append("\nerror: ", style="bold")
        body.append(error, style="red")

    if console_lines:
        body.append("\nconsole: ", style="bold")
        preview = "; ".join(console_lines)
        if len(preview) > 200:
            preview = preview[:200] + "…"
        body.append(preview, style="dim cyan")

    display_url = url if len(url) <= 80 else url[:77] + "…"
    subtitle = f"[bold]{elapsed_ms:.0f}ms[/bold]  {display_url}"

    _console.print(
        Panel(
            body,
            title=title,
            subtitle=subtitle,
            border_style="yellow" if success else "red",
            expand=False,
        )
    )


__all__ = ["execute_javascript"]
