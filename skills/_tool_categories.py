"""Tool categories — the assignable unit a skill grants.

A tool category groups related tools under a stable id; a skill grants tool
categories, never individual tools. ``tool_categories()`` returns every category
with the tools it currently grants — feature-gated static categories carry a
fixed tool set, integration-backed categories take their tools and connection
state from the integrations subsystem. Callers work only with the returned
``ToolCategory`` objects.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from typing import Any
from integrations.connection_cache import ConnectionSnapshot

@dataclass(frozen=True)
class ToolCategory:
    """A tool category and the tools it currently grants.

    Attributes:
        id: Stable identifier referenced by skill records.
        label: Human-readable name for the UI.
        description: One-line summary for the UI.
        tools: The tool callables this category currently grants — empty for an
            integration-backed category with nothing connected.
        connected: Whether the backing integration is connected — None for a
            static category, which has no connection concept.
    """

    id: str
    label: str
    description: str
    tools: list[Callable[..., Any]]
    connected: bool | None = None
    connection_id: str | None = None
    operations: tuple[dict[str, Any], ...] = ()


async def tool_categories(connections: ConnectionSnapshot = ()) -> dict[str, ToolCategory]:
    """Every tool category keyed by id, each with the tools it currently grants.

    Config-gated static categories are built once and held. Settings-backed
    categories resolve current settings; integration categories use only the
    supplied snapshot. This function never performs discovery I/O.
    """
    # Imported here, not at module top: reaching into the tools package runs its
    # __init__, which pulls tools.browser -> agent_core.events -> this package — a
    # load-time cycle. By call time agent_core.events is fully initialized.
    from tools.integrations._tool_resolution import connection_tools
    from integrations.operations import operation_for_id

    categories = dict(_static_tool_categories())
    from settings import custom_tools_enabled

    if custom_tools_enabled():
        categories["custom_tools"] = _custom_tools_category()

    for connection in connections:
        if connection.kind != "integration":
            continue
        cid = f"integration:{connection.id}"
        operations = []
        for operation_id in sorted(connection.operation_grants):
            operation = operation_for_id(operation_id)
            if operation is not None:
                operations.append(operation.public_dict())
        operations.extend(
            {"id": op.id, "title": op.title, "description": op.description}
            for op in connection.discovered_operations if op.id in connection.operation_grants
        )
        categories[cid] = ToolCategory(
            cid,
            connection.label or connection.slug,
            f"Tools from {connection.label or connection.slug}.",
            connection_tools(connection),
            connected=connection.state == "running",
            connection_id=connection.id,
            operations=tuple(operations),
        )
    return categories


# ── Static categories: config-gated, built once and held ────────────────────


@cache
def _static_tool_categories() -> dict[str, ToolCategory]:
    """The feature-gated static categories, built once from the active flags.

    A category whose tools require a disabled feature is left out; the
    browser/desktop grounding tools are included only when visual grounding is on.
    Tool imports stay inside the flag branches on purpose — don't hoist them, or a
    disabled feature's module gets imported regardless.
    """
    from config import load_config
    from tasks import add_task, begin_routine, commit_routine, list_routines, list_tasks, trigger_routine
    from tools.browser import (
        browse_page,
        click,
        close_tab,
        drag,
        execute_javascript,
        fill_field,
        go_back,
        goto,
        inspect_page,
        new_tab,
        press_and_hold,
        press_keys,
        read_page,
        save_page_content,
        scroll_page,
        select_option,
    )
    from tools.memory import forget, load_memory, remember
    from tools.virtual_computer import (
        apply_text_patch,
        grep,
        install_packages,
        list_dir,
        read_file,
        replace_in_file,
        run_bash_cmd,
        write_file,
    )
    from tools.web import fetch_url

    flags = load_config().features

    browser_tools: list[Callable[..., Any]] = [
        goto,
        new_tab,
        close_tab,
        browse_page,
        read_page,
        click,
        press_and_hold,
        fill_field,
        press_keys,
        select_option,
        scroll_page,
        go_back,
        drag,
        inspect_page,
        execute_javascript,
        save_page_content,
    ]
    if flags.visual_grounding:
        from tools.browser import browser_visual_action

        browser_tools.append(browser_visual_action)

    categories: dict[str, ToolCategory] = {
        "coding": ToolCategory(
            "coding",
            "Coding & Files",
            "Read, edit, and run code on the virtual computer.",
            [read_file, grep, list_dir, write_file, apply_text_patch, replace_in_file, run_bash_cmd, install_packages],
        ),
        "browser": ToolCategory(
            "browser",
            "Web Browsing",
            "Drive a live browser — navigate, read, click, fill forms.",
            browser_tools,
        ),
        "webfetch": ToolCategory(
            "webfetch",
            "Web Fetch",
            "Fetch a page as clean text — no browser needed.",
            [fetch_url],
        ),
        "memory": ToolCategory(
            "memory",
            "Memory",
            "Persist and recall facts across conversations.",
            [remember, forget, load_memory],
        ),
        "planning": ToolCategory(
            "planning",
            "Routine Planning",
            "Break work into tracked routines and tasks.",
            [begin_routine, add_task, commit_routine, list_routines, list_tasks, trigger_routine],
        ),
    }

    if flags.image_generation:
        from tools.generation import generate_image

        categories["image_generation"] = ToolCategory(
            "image_generation",
            "Image Generation",
            "Generate images from text prompts.",
            [generate_image],
        )

    if flags.music_generation:
        from tools.generation import generate_music

        categories["music_generation"] = ToolCategory(
            "music_generation",
            "Music Generation",
            "Generate music from text prompts.",
            [generate_music],
        )

    if flags.desktop:
        from tools.desktop import (
            describe_screen,
            desktop_shell,
            keyboard_press,
            keyboard_type,
            mouse_click,
            mouse_double_click,
            mouse_drag,
            read_screen,
            scroll,
        )

        desktop_tools: list[Callable[..., Any]] = [
            read_screen,
            describe_screen,
            mouse_click,
            mouse_double_click,
            mouse_drag,
            keyboard_type,
            keyboard_press,
            scroll,
            desktop_shell,
        ]
        if flags.visual_grounding:
            from tools.desktop import perform_visual_action

            desktop_tools.append(perform_visual_action)
        categories["desktop"] = ToolCategory(
            "desktop",
            "Desktop Control",
            "Control a GUI desktop — mouse, keyboard, screen reading.",
            desktop_tools,
        )

    return categories


@cache
def _custom_tools_category() -> ToolCategory:
    """Build the settings-backed Custom Tools category lazily."""
    from tools.custom_tools import create_custom_tool, lookup_custom_tools, run_custom_tool

    return ToolCategory(
        "custom_tools",
        "Custom Tools",
        "The agent can create, look up, and run reusable tools.",
        [create_custom_tool, lookup_custom_tools, run_custom_tool],
    )


__all__ = ["ToolCategory", "tool_categories"]
