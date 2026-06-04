"""Tool categories — the assignable unit a skill grants.

A category groups related tools under a stable id; a skill grants categories,
never individual tools. There are two kinds:

* :class:`StaticToolCategory` carries its tools directly. ``build_categories(feature_flags)``
  builds them keyed by id, consulting the flags in one place — a category whose tools
  need a disabled feature is left out, and grounding tools appear under ``browser``/
  ``desktop`` only when visual grounding is on. ``get_categories()`` memoizes it, since
  flags are fixed for the process.
* :class:`IntegrationToolCategory` names a capability instead. Its tools depend on live
  connection state, so they resolve per turn through ``integration_category_tools`` —
  never cached, and empty until an integration provides the capability.

Presentation (icons, etc.) is the frontend's concern and is not modeled here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Any

from integrations.permissions import Capability
from sdk.tools._integration_tools import integration_tools_for

if TYPE_CHECKING:
    from config import FeaturesConfig
    from tools.integrations.types import RegisteredIntegration

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StaticToolCategory:
    """A static tool category whose tools are fixed at build time.

    Attributes:
        id: Stable identifier referenced by skill records.
        label: Human-readable name for the UI.
        description: One-line summary for the UI.
        tools: The tool callables this category grants under the current flags.
    """

    id: str
    label: str
    description: str
    tools: list[Callable[..., Any]]


@dataclass(frozen=True)
class IntegrationToolCategory:
    """A category whose tools come from a connected integration capability.

    Attributes:
        id: Stable identifier referenced by skill records.
        label: Human-readable name for the UI.
        description: One-line summary for the UI.
        capability: The integration capability whose tools this category grants.
    """

    id: str
    label: str
    description: str
    capability: Capability


def build_categories(feature_flags: FeaturesConfig) -> dict[str, StaticToolCategory]:
    """The static tool categories available under the given feature flags, keyed by id.

    A category whose tools require a disabled feature is left out; the
    browser/desktop grounding tools are included only when visual grounding is on.
    Tool imports stay inside the flag branches on purpose — don't hoist them, or a
    disabled feature's module gets imported regardless.
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
    if feature_flags.visual_grounding:
        from tools.browser import browser_visual_action
        browser_tools.append(browser_visual_action)

    categories: dict[str, StaticToolCategory] = {
        "coding": StaticToolCategory(
            "coding", "Coding & Files", "Read, edit, and run code on the virtual computer.",
            [read_file, grep, list_dir, write_file, apply_text_patch, replace_in_file, run_bash_cmd, install_packages],
        ),
        "browser": StaticToolCategory(
            "browser", "Web Browsing", "Drive a live browser — navigate, read, click, fill forms.",
            browser_tools,
        ),
        "webfetch": StaticToolCategory(
            "webfetch", "Web Fetch", "Fetch a page as clean text — no browser needed.", [fetch_url],
        ),
        "memory": StaticToolCategory(
            "memory", "Memory", "Persist and recall facts across conversations.",
            [remember, forget, load_memory],
        ),
        "planning": StaticToolCategory(
            "planning", "Goal Planning", "Break work into tracked goals and tasks.",
            [begin_goal, add_task, commit_goal, list_goals, list_tasks, trigger_goal],
        ),
    }

    if feature_flags.image_generation:
        from tools.generation import generate_image
        categories["image_generation"] = StaticToolCategory(
            "image_generation", "Image Generation", "Generate images from text prompts.", [generate_image],
        )

    if feature_flags.music_generation:
        from tools.generation import generate_music
        categories["music_generation"] = StaticToolCategory(
            "music_generation", "Music Generation", "Generate music from text prompts.", [generate_music],
        )

    if feature_flags.desktop:
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
        if feature_flags.visual_grounding:
            from tools.desktop import perform_visual_action
            desktop_tools.append(perform_visual_action)
        categories["desktop"] = StaticToolCategory(
            "desktop", "Desktop Control", "Control a GUI desktop — mouse, keyboard, screen reading.",
            desktop_tools,
        )

    if feature_flags.custom_tools:
        from tools.custom_tools import create_custom_tool, lookup_custom_tools, run_custom_tool
        categories["custom_tools"] = StaticToolCategory(
            "custom_tools", "Custom Tools", "Create, look up, and run your own saved tools.",
            [create_custom_tool, lookup_custom_tools, run_custom_tool],
        )

    return categories


@cache
def get_categories() -> dict[str, StaticToolCategory]:
    """The app's static tool categories, built once from the active feature flags and held.

    Feature flags are fixed at startup, so the static tool category set is constant
    for the process. The runtime reads categories through here; tests and any
    caller needing a specific flag set call build_categories directly.
    """
    from config import load_config

    return build_categories(load_config().features)


# ── Integration categories ─────────────────────────────────────────────────
# Static definitions (one capability per id). Always grantable — a skill may
# grant `email` before any mail account is connected; it simply contributes no
# tools until one is. Resolved per turn through integration_category_tools.

INTEGRATION_CATEGORIES: dict[str, IntegrationToolCategory] = {
    "email": IntegrationToolCategory("email", "Email", "Read, search, and send mail.", Capability.EMAIL),
    "calendar": IntegrationToolCategory("calendar", "Calendar", "Manage calendar events.", Capability.CALENDAR),
    "drive": IntegrationToolCategory("drive", "Drive", "Manage cloud drive files.", Capability.DRIVE),
    "contacts": IntegrationToolCategory("contacts", "Contacts", "Look up contacts.", Capability.CONTACTS),
    "http": IntegrationToolCategory("http", "HTTP / API", "Call external HTTP APIs.", Capability.HTTP),
}


def integration_category_tools(
    category_id: str,
    integrations: Iterable[RegisteredIntegration],
) -> list[Callable[..., Any]]:
    """The tools an integration category grants given the current integrations.

    Empty for an unknown id, or for a capability no connected integration provides.
    """
    category = INTEGRATION_CATEGORIES.get(category_id)
    if category is None:
        return []
    return integration_tools_for(category.capability, integrations)
