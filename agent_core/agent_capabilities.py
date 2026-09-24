"""Compose the tools and prompt extensions active for an agent run."""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from agent_core.capabilities import AgentCapability

if TYPE_CHECKING:
    from agent_core.skills._registry import Skill

logger = logging.getLogger(__name__)

_active_agent_capabilities: ContextVar["AgentCapabilities | None"] = ContextVar(
    "active_agent_capabilities", default=None
)


class AgentCapabilities:
    """Track the tools, capabilities, and skills active for an agent run.

    Holds the agent's base tools, application-granted capabilities, and skills.
    Deduplicates tools by ``__name__`` and can produce a formatted
    prompt section for system message injection.
    """

    def __init__(self, base_tools: list[Callable[..., Any]]) -> None:
        self._base_tools: list[Callable[..., Any]] = list(base_tools)
        self._capabilities: dict[str, AgentCapability] = {}
        self._skills: dict[str, Skill] = {}  # keyed by skill id
        self._loaded_ids: set[str] = set()  # subset attached at runtime, not by the profile

    def add(self, skill: Skill) -> None:
        """Attach a profile-granted skill — the baseline. No-op if already attached.

        Baseline skills are re-derived from the profile each turn, so they're left
        out of the persisted delta and a profile edit takes effect rather than being
        pinned to old conversations.
        """
        self._attach(skill)

    def add_capability(self, capability: AgentCapability) -> None:
        """Grant an application-controlled capability to this agent."""
        self._capabilities.setdefault(capability.id, capability)

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
        for capability in self._capabilities.values():
            for tool in capability.tools:
                fname = getattr(tool, "__name__", None)
                if fname not in seen:
                    result.append(tool)
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

    def build_prompt_extensions(self) -> str:
        """Format capability and skill guidance for the system prompt.

        Returns:
            Formatted string with all capability and skill prompts, or an empty
            string when neither is present.
        """
        if not self._capabilities and not self._skills:
            return ""
        parts = [
            *(f"### {capability.name}\n{capability.prompt}" for capability in self._capabilities.values()),
            *(f"### {skill.name}\n{skill.prompt}" for skill in self._skills.values()),
        ]
        return "\n── Capabilities & Skills ──\n\n" + "\n\n".join(parts)


def get_active_agent_capabilities() -> "AgentCapabilities | None":
    """Return the AgentCapabilities for the current agent scope, or None."""
    return _active_agent_capabilities.get()


__all__ = ["AgentCapabilities", "get_active_agent_capabilities"]
