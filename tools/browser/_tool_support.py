"""Shared result-building support for agent-facing browser tools."""

from __future__ import annotations

import logging

from browser.core.browser import ActionResult
from browser.core.document import ResolvedElement
from browser.core.downloads import format_download_message
from browser.core.formatting import format_rendered_document
from browser.core.rendering import RenderedDocument
from tools.browser.events import set_result_tab

logger = logging.getLogger(__name__)


def _log_browser_panel(
    result: ActionResult,
    *,
    rendered: RenderedDocument | None,
    tool_name: str,
    resolution: ResolvedElement | None = None,
) -> None:
    """Emit a single Rich panel summarising a browser tool call."""
    if not logger.isEnabledFor(logging.INFO):
        return

    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    table = Table(show_header=False, expand=False, padding=(0, 1))
    table.add_column("Phase", style="bold")
    table.add_column("Duration", justify="right")
    table.add_column("Status")

    if result.action_ms > 0:
        table.add_row("interaction", f"{result.action_ms:.0f}ms", "")
    if result.navigation_wait_ms > 0:
        table.add_row("navigation wait", f"{result.navigation_wait_ms:.0f}ms", "")

    settle = rendered.settle_timings if rendered is not None else None
    if settle is not None:
        for name, duration_ms, timed_out in settle.phases:
            status = "[yellow]timeout[/yellow]" if timed_out else "[green]ok[/green]"
            table.add_row(name, f"{duration_ms:.0f}ms", status)
        if settle.error:
            table.add_row("error", "", f"[red]{settle.error}[/red]")

    if rendered is not None and rendered.node_count > 0:
        render_ms = rendered.dom_walk_ms + rendered.render_ms
        table.add_row("render", f"{render_ms:.0f}ms", f"{rendered.node_count} nodes")

    settle_total = settle.total_ms if settle else 0
    render_total = (rendered.dom_walk_ms + rendered.render_ms) if rendered else 0
    total_ms = result.action_ms + result.navigation_wait_ms + settle_total + render_total

    url = rendered.url if rendered else ""
    display_url = url if len(url) <= 80 else url[:77] + "…"

    title_parts: list[str] = [f"[bold cyan]{tool_name or 'browser'}[/bold cyan]"]
    if resolution:
        title_parts.append(f"ref={resolution.ref}")
    title = "  ".join(title_parts)

    parts: list[str] = [f"total=[bold]{total_ms:.0f}ms[/bold]"]
    if display_url:
        parts.append(display_url)
    if result.document_transition:
        parts.append(f"document: {result.document_transition}")
    if result.download:
        parts.append(f"download: {result.download.filename}")
    subtitle = "  ".join(parts)

    Console(stderr=True).print(
        Panel(
            table,
            title=title,
            subtitle=subtitle,
            border_style="dim",
            expand=False,
        )
    )


async def format_action_result(
    result: ActionResult,
    *,
    tool_name: str,
    resolution: ResolvedElement | None = None,
) -> str:
    """Render and format the tab produced by a coordinated browser action."""
    set_result_tab(result.tab)
    if result.download is not None:
        _log_browser_panel(
            result,
            rendered=None,
            tool_name=tool_name,
            resolution=resolution,
        )
        return format_download_message(result.download)

    rendered = await result.tab.render_document(result.navigation_response)
    _log_browser_panel(
        result,
        rendered=rendered,
        tool_name=tool_name,
        resolution=resolution,
    )
    return format_rendered_document(rendered, tab_id=result.tab.id)


__all__ = [
    "_log_browser_panel",
    "format_action_result",
]
