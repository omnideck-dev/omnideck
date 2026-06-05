"""Skill system: progressive tool loading for agents.

Provides AgentState (tracks base tools and loaded skills), the Skill model,
skill registry, and the load_skill / list_available_skills meta-tools.
"""

from ._registry import Skill, get_skill, list_skills, register_skill
from ._resolve import (
    build_agent_state,
    persist_loaded_skills,
    resolve_skill,
    resolve_skill_by_name,
)
from ._tools import list_available_skills, load_skill
from .agent_state import AgentState, get_active_agent_state

__all__ = [
    "AgentState",
    "Skill",
    "build_agent_state",
    "get_active_agent_state",
    "get_skill",
    "list_available_skills",
    "list_skills",
    "load_skill",
    "persist_loaded_skills",
    "register_skill",
    "resolve_skill",
    "resolve_skill_by_name",
]
