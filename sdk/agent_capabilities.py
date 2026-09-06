"""Compose the tools and prompt extensions active for an agent run."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from sdk.capabilities import AgentCapability

if TYPE_CHECKING:
    from agents._agent_profiles import AgentProfile
    from sdk.skills._registry import Skill

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


def _base_tools(*, allow_spawn: bool, allow_load_skills: bool) -> list[Callable[..., Any]]:
    """Return always-on tools plus the profile's toggle-gated tool pairs."""
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


async def build_agent_capabilities(
    profile: AgentProfile,
    *,
    conversation_id: str | None = None,
) -> AgentCapabilities:
    """Build one run's state from agent settings, capabilities, and skills."""
    from sdk.skills._policy import is_reserved_skill_id
    from sdk.skills._resolve import resolve_skill

    state = AgentCapabilities(
        _base_tools(
            allow_spawn=profile.allow_spawn,
            allow_load_skills=profile.allow_load_skills,
        )
    )
    for skill_id in profile.skills:
        if is_reserved_skill_id(skill_id):
            continue
        skill = await resolve_skill(skill_id)
        if skill is None:
            logger.warning(
                "profile %r references unknown skill %r; skipping",
                profile.id,
                skill_id,
            )
            continue
        state.add(skill)

    if profile.browser_profile_id is not None:
        from tools.browser.capability import browser_capability

        state.add_capability(await browser_capability())

    if conversation_id is not None:
        from conversations import load_loaded_skills

        await _restore_persisted_loaded_skills(
            state,
            load_loaded_skills(conversation_id),
        )
    return state


async def _restore_persisted_loaded_skills(
    agent_capabilities: AgentCapabilities,
    skill_ids: Iterable[str],
) -> None:
    """Resolve and restore the conversation's dynamically loaded skills."""
    from sdk.skills._policy import is_reserved_skill_id
    from sdk.skills._resolve import resolve_skill

    for skill_id in skill_ids:
        if is_reserved_skill_id(skill_id) or skill_id in agent_capabilities.skill_ids:
            continue
        skill = await resolve_skill(skill_id)
        if skill is None:
            logger.warning("loaded skill %r no longer resolves; skipping", skill_id)
            continue
        agent_capabilities.load(skill)


def persist_loaded_skills(agent_capabilities: AgentCapabilities, conversation_id: str) -> None:
    """Persist the conversation's dynamically loaded skill IDs."""
    from conversations import save_loaded_skills

    save_loaded_skills(conversation_id, agent_capabilities.loaded_skill_ids)


__all__ = [
    "AgentCapabilities",
    "build_agent_capabilities",
    "get_active_agent_capabilities",
    "persist_loaded_skills",
]
