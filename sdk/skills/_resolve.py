"""Resolve stored skill records into runtime skills and build agent state.

A SkillRecord names the tool categories a skill grants; resolution turns those
ids into live tool callables (via ``tool_categories``) and bundles them into a
runtime Skill (prompt + tools).

``build_agent_state`` assembles a profile's AgentState: the toggle-gated base
tools, plus each of the profile's skills added as a unit — so a skill's prompt
*and* its tools both apply. Given a conversation id, it also restores the skills
that were loaded mid-conversation in earlier turns; ``persist_loaded_skills``
writes them back. The conversation metadata is this package's to read and write
— callers hand over a conversation id, not a list of skill ids.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any

from conversations import load_loaded_skills, save_loaded_skills
from sdk.skills._registry import Skill
from sdk.skills._store import get_skill_record, list_skill_records
from sdk.skills.agent_state import AgentState

if TYPE_CHECKING:
    from agents._agent_profiles import AgentProfile
    from sdk.skills._store import SkillRecord

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
    # Imported at call time: the category registry pulls in the tool packages,
    # which depend on sdk.events, which imports this package — a load-time cycle.
    from sdk.tools._categories import tool_categories

    categories = await tool_categories()
    tools: list[Callable[..., Any]] = []
    for cid in record.tool_categories:
        category = categories.get(cid)
        if category is None:
            logger.warning("skill grants unknown tool category %r", cid)
            continue
        tools.extend(category.tools)
    return Skill(id=record.id, name=record.name, description=record.description, prompt=record.prompt, tools=tools)


def _base_tools(*, allow_spawn: bool, allow_load_skills: bool) -> list[Callable[..., Any]]:
    """The always-on tools plus the toggle-gated spawn/load pairs.

    Imports are function-local: spawn_agent and load_skill reach back into the
    composition path, so importing them at module load would cycle.
    """
    from tools.misc import datetime_tool
    from tools.scratchpad import recall_from_scratchpad, save_to_scratchpad
    from tools.virtual_computer.describe_image import describe_image
    from tools.virtual_computer.file_output import send_file
    from tools.virtual_computer.play_audio import play_audio

    tools: list[Callable[..., Any]] = [
        save_to_scratchpad,
        recall_from_scratchpad,
        send_file,
        play_audio,
        describe_image,
        datetime_tool,
    ]
    if allow_spawn:
        from agents._list_profiles_tool import list_agent_profiles
        from sdk.tools._spawn_agent import spawn_agent

        tools += [spawn_agent, list_agent_profiles]
    if allow_load_skills:
        from sdk.skills._tools import list_available_skills, load_skill

        tools += [load_skill, list_available_skills]
    return tools


async def build_agent_state(profile: AgentProfile, *, conversation_id: str | None = None) -> AgentState:
    """The AgentState for an agent built from ``profile``.

    The toggle-gated base tools (spawn/load per the profile's autonomy toggles),
    plus each of the profile's skills resolved and added as a unit — so its
    prompt and tools both apply, and ``AgentState`` dedups tools by name. A
    profile skill that no longer resolves is skipped with a warning.

    With a ``conversation_id``, the skills loaded mid-conversation in earlier
    turns are restored on top (read from conversation metadata) — so a turn's
    state is the profile's skills plus whatever that conversation has loaded.
    Omit it for one-off agents (tasks, sub-agents) with no conversation history.
    """
    state = AgentState(_base_tools(allow_spawn=profile.allow_spawn, allow_load_skills=profile.allow_load_skills))
    for skill_id in profile.skills:
        skill = await resolve_skill(skill_id)
        if skill is None:
            logger.warning("profile %r references unknown skill %r; skipping", profile.id, skill_id)
            continue
        state.add(skill)
    if conversation_id is not None:
        await _restore_skills(state, load_loaded_skills(conversation_id))
    return state


async def _restore_skills(agent_state: AgentState, skill_ids: Iterable[str]) -> None:
    """Resolve previously-loaded skills by id and add them to ``agent_state``.

    Ids already loaded (e.g. granted by the profile) are skipped, and an id that
    no longer resolves (the skill was deleted) is skipped with a warning — so
    stale metadata is harmless.
    """
    for skill_id in skill_ids:
        if skill_id in agent_state.loaded_skill_ids:
            continue
        skill = await resolve_skill(skill_id)
        if skill is None:
            logger.warning("loaded skill %r no longer resolves; skipping", skill_id)
            continue
        agent_state.add(skill)


def persist_loaded_skills(agent_state: AgentState, conversation_id: str) -> None:
    """Write the conversation's loaded skills to metadata so they survive turns.

    The mirror of the restore that ``build_agent_state`` does for a conversation:
    the ids re-resolve into the next turn's state.
    """
    save_loaded_skills(conversation_id, agent_state.loaded_skill_ids)


__all__ = [
    "build_agent_state",
    "persist_loaded_skills",
    "resolve_skill",
    "resolve_skill_by_name",
]
