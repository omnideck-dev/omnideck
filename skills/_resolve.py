"""Resolve stored skill records into runtime skills.

A SkillRecord names the tool categories a skill grants; resolution turns those
ids into live tool callables (via ``tool_categories``) and bundles them into a
runtime Skill (prompt + tools).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from skills._policy import is_restricted_tool_category
from agent_core.skills import Skill
from skills._store import get_skill_record, list_skill_records
from skills._tool_categories import tool_categories

if TYPE_CHECKING:
    from skills._store import SkillRecord

logger = logging.getLogger(__name__)


async def resolve_skill(skill_id: str) -> Skill | None:
    """Resolve a skill record by id into a runtime Skill, or None if unknown."""
    return await _resolve(get_skill_record(skill_id))


async def resolve_skill_by_name(name: str) -> Skill | None:
    """Resolve a skill record by its unique name, or None if unknown.

    For the LLM-facing ``load_skill(name)`` path; names are unique, so at most
    one record matches.
    """
    return await _resolve(next((r for r in list_skill_records() if r.name == name), None))


async def _resolve(record: SkillRecord | None) -> Skill | None:
    """Build a runtime Skill from a record, mapping its tool categories to tools."""
    if record is None:
        return None
    categories = await tool_categories()
    tools: list[Callable[..., Any]] = []
    for cid in record.tool_categories:
        if is_restricted_tool_category(cid):
            logger.warning("skill %r cannot grant restricted tool category %r", record.id, cid)
            continue
        category = categories.get(cid)
        if category is None:
            logger.warning("skill grants unknown tool category %r", cid)
            continue
        tools.extend(category.tools)
    return Skill(id=record.id, name=record.name, description=record.description, prompt=record.prompt, tools=tools)


__all__ = [
    "resolve_skill",
    "resolve_skill_by_name",
]
