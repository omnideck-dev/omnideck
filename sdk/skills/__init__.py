"""Skill system: progressive tool loading for agents.

Provides the Skill model, skill resolution, and the load_skill /
list_available_skills meta-tools.
"""

from ._registry import Skill
from ._resolve import (
    resolve_skill,
    resolve_skill_by_name,
)
from ._tool_categories import ToolCategory, tool_categories
from ._tools import list_available_skills, load_skill

__all__ = [
    "Skill",
    "ToolCategory",
    "list_available_skills",
    "load_skill",
    "resolve_skill",
    "resolve_skill_by_name",
    "tool_categories",
]
