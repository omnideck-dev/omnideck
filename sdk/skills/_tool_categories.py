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

from integrations.permissions import Capability


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


async def tool_categories() -> dict[str, ToolCategory]:
    """Every tool category keyed by id, each with the tools it currently grants.

    Static categories come from the active feature flags (built once and held);
    integration-backed categories take their current tools and connection state
    from the integrations subsystem, so a category whose capability nothing
    provides is listed with no tools.
    """
    # Imported here, not at module top: reaching into the tools package runs its
    # __init__, which pulls tools.browser -> sdk.events -> this package — a
    # load-time cycle. By call time sdk.events is fully initialized.
    from tools.integrations import CapabilityTools, integration_tools_by_capability

    categories = dict(_static_tool_categories())
    by_capability = await integration_tools_by_capability()
    for cid, integration in _INTEGRATION_TOOL_CATEGORIES.items():
        backed = by_capability.get(integration.capability, CapabilityTools([], available=False))
        # The category is "connected" when a connected integration makes its capability available.
        categories[cid] = ToolCategory(
            cid,
            integration.label,
            integration.description,
            backed.tools,
            connected=backed.available,
        )
    return categories


# ── Static categories: feature-gated, built once and held ────────────────────


@cache
def _static_tool_categories() -> dict[str, ToolCategory]:
    """The feature-gated static categories, built once from the active flags.

    A category whose tools require a disabled feature is left out; the
    browser/desktop grounding tools are included only when visual grounding is on.
    Tool imports stay inside the flag branches on purpose — don't hoist them, or a
    disabled feature's module gets imported regardless.
    """
    from config import load_config
    from tasks import add_task, begin_goal, commit_goal, list_goals, list_tasks, trigger_goal
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
        goto, new_tab, close_tab, browse_page, read_page, click, press_and_hold,
        fill_field, press_keys, select_option, scroll_page, go_back, drag,
        inspect_page, execute_javascript, save_page_content,
    ]
    if flags.visual_grounding:
        from tools.browser import browser_visual_action
        browser_tools.append(browser_visual_action)

    categories: dict[str, ToolCategory] = {
        "coding": ToolCategory(
            "coding", "Coding & Files", "Read, edit, and run code on the virtual computer.",
            [read_file, grep, list_dir, write_file, apply_text_patch, replace_in_file, run_bash_cmd, install_packages],
        ),
        "browser": ToolCategory(
            "browser", "Web Browsing", "Drive a live browser — navigate, read, click, fill forms.",
            browser_tools,
        ),
        "webfetch": ToolCategory(
            "webfetch", "Web Fetch", "Fetch a page as clean text — no browser needed.", [fetch_url],
        ),
        "memory": ToolCategory(
            "memory", "Memory", "Persist and recall facts across conversations.",
            [remember, forget, load_memory],
        ),
        "planning": ToolCategory(
            "planning", "Goal Planning", "Break work into tracked goals and tasks.",
            [begin_goal, add_task, commit_goal, list_goals, list_tasks, trigger_goal],
        ),
    }

    if flags.image_generation:
        from tools.generation import generate_image
        categories["image_generation"] = ToolCategory(
            "image_generation", "Image Generation", "Generate images from text prompts.", [generate_image],
        )

    if flags.music_generation:
        from tools.generation import generate_music
        categories["music_generation"] = ToolCategory(
            "music_generation", "Music Generation", "Generate music from text prompts.", [generate_music],
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
            read_screen, describe_screen, mouse_click, mouse_double_click,
            mouse_drag, keyboard_type, keyboard_press, scroll, desktop_shell,
        ]
        if flags.visual_grounding:
            from tools.desktop import perform_visual_action
            desktop_tools.append(perform_visual_action)
        categories["desktop"] = ToolCategory(
            "desktop", "Desktop Control", "Control a GUI desktop — mouse, keyboard, screen reading.",
            desktop_tools,
        )

    if flags.custom_tools:
        from tools.custom_tools import create_custom_tool, lookup_custom_tools, run_custom_tool
        categories["custom_tools"] = ToolCategory(
            "custom_tools", "Custom Tools", "Create, look up, and run your own saved tools.",
            [create_custom_tool, lookup_custom_tools, run_custom_tool],
        )

    return categories


# ── Integration categories: a capability per id, tools resolved per turn ──────


@dataclass(frozen=True)
class _IntegrationToolCategory:
    label: str
    description: str
    capability: Capability


_INTEGRATION_TOOL_CATEGORIES: dict[str, _IntegrationToolCategory] = {
    "email": _IntegrationToolCategory("Email", "Read, search, and send mail.", Capability.EMAIL),
    "calendar": _IntegrationToolCategory("Calendar", "Manage calendar events.", Capability.CALENDAR),
    "drive": _IntegrationToolCategory("Drive", "Manage cloud drive files.", Capability.DRIVE),
    "contacts": _IntegrationToolCategory("Contacts", "Look up contacts.", Capability.CONTACTS),
    "http": _IntegrationToolCategory("HTTP / API", "Call external HTTP APIs.", Capability.HTTP),
}


__all__ = ["ToolCategory", "tool_categories"]
