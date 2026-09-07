"""Policy for application-reserved skills and restricted tool categories."""

from __future__ import annotations

from collections.abc import Iterable

LEGACY_BROWSER_SKILL_ID = "browser"
RESERVED_SKILL_IDS = frozenset({LEGACY_BROWSER_SKILL_ID})
RESTRICTED_TOOL_CATEGORY_IDS = frozenset({"browser"})


def is_reserved_skill_id(skill_id: str) -> bool:
    """Return whether an ID belongs to an application capability."""
    return skill_id in RESERVED_SKILL_IDS


def is_restricted_tool_category(category_id: str) -> bool:
    """Return whether user-editable skills may grant a tool category."""
    return category_id in RESTRICTED_TOOL_CATEGORY_IDS


def strip_reserved_skills(skill_ids: Iterable[str]) -> list[str]:
    """Remove obsolete application-capability IDs from skill assignments."""
    return [skill_id for skill_id in skill_ids if not is_reserved_skill_id(skill_id)]


def grants_restricted_tool_category(category_ids: Iterable[str]) -> bool:
    """Return whether a skill attempts to grant a restricted category."""
    return any(is_restricted_tool_category(category_id) for category_id in category_ids)


__all__ = [
    "LEGACY_BROWSER_SKILL_ID",
    "RESTRICTED_TOOL_CATEGORY_IDS",
    "RESERVED_SKILL_IDS",
    "grants_restricted_tool_category",
    "is_reserved_skill_id",
    "is_restricted_tool_category",
    "strip_reserved_skills",
]
