"""Tool categories — the assignable unit a skill grants.

A category groups related tools under a stable id. Every tool belongs to exactly
one category (or the always-on base set, which is not a category and is never
grantable). Categories are the only tool grouping a skill can grant.

Standard categories carry a lazy loader that imports their tools on demand, so
heavy/optional dependencies (browser, desktop, generation) stay out of the
import path until a category is actually resolved. Integration categories —
keyed by capability and resolved through the integration permission layer — are
added separately and carry no loader.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from config import FeaturesConfig

logger = logging.getLogger(__name__)

ToolLoader = Callable[[], list[Callable[..., Any]]]

# Local UI-TARS grounding tools, matched by name so the strip never has to
# import the browser/desktop modules. They shell out to the local inference
# server; with visual grounding off they should be invisible to the agent.
_GROUNDING_TOOL_NAMES = frozenset({"browser_visual_action", "perform_visual_action"})


@dataclass(frozen=True)
class ToolCategory:
    """An app-defined group of tools that a skill can grant.

    Attributes:
        id: Stable identifier referenced by skill records.
        label: Human-readable name for the catalog.
        description: One-line summary for the catalog.
        icon: Bootstrap Icons name (e.g. ``bi-terminal``) for the UI.
        kind: ``std`` for code-defined tool groups, ``integration`` for
            capability-backed groups resolved through the integration layer.
        feature: Name of the FeaturesConfig flag that must be truthy for this
            category to be available, or None if always available.
        loader: Returns the category's tool callables (standard categories
            only). None for integration categories.
    """

    id: str
    label: str
    description: str
    icon: str
    kind: Literal["std", "integration"] = "std"
    feature: str | None = None
    loader: ToolLoader | None = None


# ── Standard category loaders ──────────────────────────────────────────────
# Each loader imports only its own package, keeping unrelated heavy deps out of
# the path when a category is resolved.

def _coding_tools() -> list[Callable[..., Any]]:
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

    return [
        read_file,
        grep,
        list_dir,
        write_file,
        apply_text_patch,
        replace_in_file,
        run_bash_cmd,
        install_packages,
    ]


def _browser_tools() -> list[Callable[..., Any]]:
    from tools.browser import (
        browse_page,
        browser_visual_action,
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

    return [
        goto,
        new_tab,
        close_tab,
        browse_page,
        read_page,
        click,
        press_and_hold,
        browser_visual_action,
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


def _webfetch_tools() -> list[Callable[..., Any]]:
    from tools.web import fetch_url

    return [fetch_url]


def _memory_tools() -> list[Callable[..., Any]]:
    from tools.memory import forget, load_memory, remember

    return [remember, forget, load_memory]


def _planning_tools() -> list[Callable[..., Any]]:
    from tasks import add_task, begin_goal, commit_goal, list_goals, list_tasks, trigger_goal

    return [begin_goal, add_task, commit_goal, list_goals, list_tasks, trigger_goal]


def _image_generation_tools() -> list[Callable[..., Any]]:
    from tools.generation import generate_image

    return [generate_image]


def _music_generation_tools() -> list[Callable[..., Any]]:
    from tools.generation import generate_music

    return [generate_music]


def _custom_tools() -> list[Callable[..., Any]]:
    from tools.custom_tools import create_custom_tool, lookup_custom_tools, run_custom_tool

    return [create_custom_tool, lookup_custom_tools, run_custom_tool]


def _desktop_tools() -> list[Callable[..., Any]]:
    from tools.desktop import (
        describe_screen,
        desktop_shell,
        keyboard_press,
        keyboard_type,
        mouse_click,
        mouse_double_click,
        mouse_drag,
        perform_visual_action,
        read_screen,
        scroll,
    )

    return [
        read_screen,
        describe_screen,
        perform_visual_action,
        mouse_click,
        mouse_double_click,
        mouse_drag,
        keyboard_type,
        keyboard_press,
        scroll,
        desktop_shell,
    ]


_STD_CATEGORIES: list[ToolCategory] = [
    ToolCategory(
        id="coding",
        label="Coding & Files",
        description="Read, edit, and run code on the virtual computer.",
        icon="bi-terminal",
        loader=_coding_tools,
    ),
    ToolCategory(
        id="browser",
        label="Web Browsing",
        description="Drive a live browser — navigate, read, click, fill forms.",
        icon="bi-globe2",
        loader=_browser_tools,
    ),
    ToolCategory(
        id="webfetch",
        label="Web Fetch",
        description="Fetch a page as clean text — no browser needed.",
        icon="bi-file-earmark-text",
        loader=_webfetch_tools,
    ),
    ToolCategory(
        id="memory",
        label="Memory",
        description="Persist and recall facts across conversations.",
        icon="bi-journal-text",
        loader=_memory_tools,
    ),
    ToolCategory(
        id="planning",
        label="Goal Planning",
        description="Break work into tracked goals and tasks.",
        icon="bi-list-task",
        loader=_planning_tools,
    ),
    ToolCategory(
        id="image_generation",
        label="Image Generation",
        description="Generate images from text prompts.",
        icon="bi-image",
        feature="image_generation",
        loader=_image_generation_tools,
    ),
    ToolCategory(
        id="music_generation",
        label="Music Generation",
        description="Generate music from text prompts.",
        icon="bi-music-note-beamed",
        feature="music_generation",
        loader=_music_generation_tools,
    ),
    ToolCategory(
        id="desktop",
        label="Desktop Control",
        description="Control a GUI desktop — mouse, keyboard, screen reading.",
        icon="bi-display",
        feature="desktop",
        loader=_desktop_tools,
    ),
    ToolCategory(
        id="custom_tools",
        label="Custom Tools",
        description="Create, look up, and run your own saved tools.",
        icon="bi-tools",
        feature="custom_tools",
        loader=_custom_tools,
    ),
]

_BY_ID: dict[str, ToolCategory] = {c.id: c for c in _STD_CATEGORIES}


def std_categories() -> list[ToolCategory]:
    """All standard categories, regardless of feature flags."""
    return list(_STD_CATEGORIES)


def get_category(category_id: str) -> ToolCategory | None:
    """Look up a standard category by id, or None if unknown."""
    return _BY_ID.get(category_id)


def _feature_enabled(category: ToolCategory, features: FeaturesConfig) -> bool:
    return category.feature is None or bool(getattr(features, category.feature, False))


def list_categories(features: FeaturesConfig) -> list[ToolCategory]:
    """Standard categories available under the given feature flags.

    A feature-gated category whose flag is off is omitted entirely — a disabled
    feature's tools never appear in the catalog or as something a skill can grant.
    """
    return [c for c in _STD_CATEGORIES if _feature_enabled(c, features)]


def category_tools(category_id: str, features: FeaturesConfig) -> list[Callable[..., Any]]:
    """Resolve a standard category's tool callables for the given features.

    Returns an empty list for an unknown id or a feature-gated-off category.
    Local grounding tools are dropped when visual grounding is disabled.
    """
    category = _BY_ID.get(category_id)
    if category is None or category.loader is None:
        return []
    if not _feature_enabled(category, features):
        return []
    tools = category.loader()
    if not features.visual_grounding:
        tools = [t for t in tools if getattr(t, "__name__", None) not in _GROUNDING_TOOL_NAMES]
    return tools
