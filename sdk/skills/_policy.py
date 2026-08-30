"""Canonical policy for application-managed skills and tool categories."""

from __future__ import annotations

from collections.abc import Iterable

BROWSER_CAPABILITY_ID = "browser"
INTERNAL_SKILL_IDS = frozenset({BROWSER_CAPABILITY_ID})
INTERNAL_TOOL_CATEGORY_IDS = frozenset({BROWSER_CAPABILITY_ID})


def is_internal_skill(skill_id: str) -> bool:
    """Return whether a skill is managed by the application rather than users."""
    return skill_id in INTERNAL_SKILL_IDS


def is_internal_tool_category(category_id: str) -> bool:
    """Return whether a category is granted only by application policy."""
    return category_id in INTERNAL_TOOL_CATEGORY_IDS


def strip_internal_skills(skill_ids: Iterable[str]) -> list[str]:
    """Remove application-managed capabilities from user-editable assignments."""
    return [skill_id for skill_id in skill_ids if not is_internal_skill(skill_id)]


def grants_internal_tool_category(category_ids: Iterable[str]) -> bool:
    """Return whether a user-editable skill attempts to grant an internal category."""
    return any(is_internal_tool_category(category_id) for category_id in category_ids)


__all__ = [
    "BROWSER_CAPABILITY_ID",
    "INTERNAL_SKILL_IDS",
    "INTERNAL_TOOL_CATEGORY_IDS",
    "grants_internal_tool_category",
    "is_internal_skill",
    "is_internal_tool_category",
    "strip_internal_skills",
]
