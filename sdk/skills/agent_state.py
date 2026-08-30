"""Tracks base tools and dynamically loaded skills for an agent scope."""

import logging
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

from ._registry import Skill

logger = logging.getLogger(__name__)

_active_agent_state: ContextVar["AgentState | None"] = ContextVar("skills_active_agent_state", default=None)


class AgentState:
    """Tracks base tools and dynamically loaded skills.

    Holds the agent's base tools plus any skills loaded at runtime.
    Deduplicates tools by ``__name__`` and can produce a formatted
    prompt section for system message injection.
    """

    def __init__(self, base_tools: list[Callable[..., Any]]) -> None:
        self._base_tools: list[Callable[..., Any]] = list(base_tools)
        self._skills: dict[str, Skill] = {}  # keyed by skill id
        self._loaded_ids: set[str] = set()  # subset attached at runtime, not by the profile

    def add(self, skill: Skill) -> None:
        """Attach a profile-granted skill — the baseline. No-op if already attached.

        Baseline skills are re-derived from the profile each turn, so they're left
        out of the persisted delta and a profile edit takes effect rather than being
        pinned to old conversations.
        """
        self._attach(skill)

    def load(self, skill: Skill) -> None:
        """Attach a skill loaded at runtime — by the agent mid-conversation or
        restored from one. No-op if already attached.

        These make up the delta a conversation remembers across turns (see
        ``loaded_skill_ids``).
        """
        if self._attach(skill):
            self._loaded_ids.add(skill.id)

    def _attach(self, skill: Skill) -> bool:
        """Insert the skill; return True if newly attached, False if already present."""
        if skill.id in self._skills:
            return False
        self._skills[skill.id] = skill
        logger.info(
            "Loaded skill '%s' (%d tools)",
            skill.name,
            len(skill.tools),
        )
        return True

    @property
    def tools(self) -> list[Callable[..., Any]]:
        """Base tools + skill tools, deduplicated by ``__name__``."""
        seen: set[str | None] = set()
        result: list[Callable[..., Any]] = []
        for t in self._base_tools:
            fname = getattr(t, "__name__", None)
            if fname not in seen:
                result.append(t)
                seen.add(fname)
        for skill in self._skills.values():
            for t in skill.tools:
                fname = getattr(t, "__name__", None)
                if fname not in seen:
                    result.append(t)
                    seen.add(fname)
        return result

    @property
    def skill_ids(self) -> frozenset[str]:
        """Ids of all attached skills — the profile's baseline plus runtime-loaded."""
        return frozenset(self._skills)

    @property
    def loaded_skill_ids(self) -> frozenset[str]:
        """Ids attached at runtime (loaded or restored), excluding the profile's own.

        This is the delta a conversation persists across turns — profile skills are
        re-derived each turn, so they're deliberately left out.
        """
        return frozenset(self._loaded_ids)

    def build_skill_prompt(self) -> str:
        """Format loaded skill prompts for system message injection.

        Returns:
            Formatted string with all skill prompts, or empty string
            if no skills are loaded.
        """
        if not self._skills:
            return ""
        parts = [f"### {s.name}\n{s.prompt}" for s in self._skills.values()]
        return "\n── Loaded Skills ──\n\n" + "\n\n".join(parts)


def get_active_agent_state() -> "AgentState | None":
    """Return the AgentState for the current agent scope, or None."""
    return _active_agent_state.get()
