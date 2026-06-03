"""Tool categories — the assignable unit a skill grants.

A category groups related tools under a stable id. Every tool belongs to exactly
one category (or the always-on base set, which is not a category and is never
grantable). Categories are the only tool grouping a skill can grant.

``build_categories(features)`` is the pure builder: given feature flags it
returns the categories keyed by id — each carrying its own tools — consulting
the flags in this one place (a category whose tools need a disabled feature
isn't included, and the grounding tools appear under ``browser``/``desktop``
only when visual grounding is on). ``get_categories()`` is the runtime
accessor: feature flags are fixed for the process, so it builds the dict once
and holds it. Imports happen inside the builder, so importing this module stays
cheap and an optional/heavy package loads only on first build, when a flag
enables it.

Integration categories depend on live connection state and are resolved
separately per turn — they are deliberately not held here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from config import FeaturesConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolCategory:
    """A group of tools a skill can grant, with its catalog metadata.

    Attributes:
        id: Stable identifier referenced by skill records.
        label: Human-readable name for the catalog.
        description: One-line summary for the catalog.
        tools: The tool callables this category grants under the current flags.
    """

    id: str
    label: str
    description: str
    tools: list[Callable[..., Any]] = field(default_factory=list)


def build_categories(features: FeaturesConfig) -> dict[str, ToolCategory]:
    """The categories available under the given feature flags, keyed by id.

    A category whose tools require a disabled feature is left out; the
    browser/desktop grounding tools are included only when visual grounding is
    on. Imports are done here so a disabled feature's (possibly heavy) package is
    never imported.
    """
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

    browser_tools: list[Callable[..., Any]] = [
        goto, new_tab, close_tab, browse_page, read_page, click, press_and_hold,
        fill_field, press_keys, select_option, scroll_page, go_back, drag,
        inspect_page, execute_javascript, save_page_content,
    ]
    if features.visual_grounding:
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
        "webfetch": ToolCategory("webfetch", "Web Fetch", "Fetch a page as clean text — no browser needed.", [fetch_url]),
        "memory": ToolCategory("memory", "Memory", "Persist and recall facts across conversations.", [remember, forget, load_memory]),
        "planning": ToolCategory(
            "planning", "Goal Planning", "Break work into tracked goals and tasks.",
            [begin_goal, add_task, commit_goal, list_goals, list_tasks, trigger_goal],
        ),
    }

    if features.image_generation:
        from tools.generation import generate_image
        categories["image_generation"] = ToolCategory(
            "image_generation", "Image Generation", "Generate images from text prompts.", [generate_image],
        )

    if features.music_generation:
        from tools.generation import generate_music
        categories["music_generation"] = ToolCategory(
            "music_generation", "Music Generation", "Generate music from text prompts.", [generate_music],
        )

    if features.desktop:
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
        if features.visual_grounding:
            from tools.desktop import perform_visual_action
            desktop_tools.append(perform_visual_action)
        categories["desktop"] = ToolCategory(
            "desktop", "Desktop Control", "Control a GUI desktop — mouse, keyboard, screen reading.", desktop_tools,
        )

    if features.custom_tools:
        from tools.custom_tools import create_custom_tool, lookup_custom_tools, run_custom_tool
        categories["custom_tools"] = ToolCategory(
            "custom_tools", "Custom Tools", "Create, look up, and run your own saved tools.",
            [create_custom_tool, lookup_custom_tools, run_custom_tool],
        )

    return categories


@cache
def get_categories() -> dict[str, ToolCategory]:
    """The app's categories, built once from the active feature flags and held.

    Feature flags are fixed at startup, so the standard category set is constant
    for the process. The runtime reads categories through here; tests and any
    caller needing a specific flag set call build_categories directly.
    """
    from config import load_config

    return build_categories(load_config().features)
