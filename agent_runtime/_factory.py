"""Translate saved profiles and application services into SDK execution inputs."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from agents import AgentProfile, get_agent_profile
from sdk.agent import Agent
from sdk.agent_capabilities import AgentCapabilities
from sdk.providers import Provider
from providers import get_provider
from tools.memory import load_memory

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedAgent:
    """Fresh execution inputs; mutable capabilities are never shared across agents."""

    profile: AgentProfile
    agent: Agent
    capabilities: AgentCapabilities
    provider: Provider
    system_prompt: str


class AgentFactory:
    """Own application policy for profile, capability, and prompt composition."""

    @staticmethod
    def resolve_profile(profile_id: str | None) -> AgentProfile:
        if not profile_id:
            raise RuntimeError("profile_id is required")
        profile = get_agent_profile(profile_id)
        if profile is None:
            raise RuntimeError(f"Agent profile '{profile_id}' not found")
        if not profile.model:
            raise ValueError("No model configured. Select a model in the agent profile settings.")
        return profile

    async def prepare(
        self,
        profile: AgentProfile,
        *,
        spawn_agent: Callable[..., Any],
        name: str | None = None,
        restore_from_conversation: str | None = None,
        include_memory: bool = False,
    ) -> PreparedAgent:
        agent = self.build_agent(profile, name=name)
        capabilities = await self.build_capabilities(
            profile,
            spawn_agent=spawn_agent,
            conversation_id=restore_from_conversation,
        )
        instruction = agent.instruction
        memory = load_memory() if include_memory else {}
        if memory:
            lines = "\n".join(f"  {key}: {entry.value}" for key, entry in memory.items())
            sep = "─" * 64
            instruction = (
                f"\n── Memory (persisted across sessions) ──────────────────────────\n{lines}\n{sep}\n" + instruction
            )
        return PreparedAgent(profile, agent, capabilities, get_provider(agent.provider), instruction)

    async def build_capabilities(
        self,
        profile: AgentProfile,
        *,
        spawn_agent: Callable[..., Any],
        conversation_id: str | None = None,
    ) -> AgentCapabilities:
        """Build one run's state from agent settings, capabilities, and skills."""
        from skills._policy import is_reserved_skill_id
        from skills._resolve import resolve_skill

        state = AgentCapabilities(
            _base_tools(
                allow_spawn=profile.allow_spawn,
                spawn_agent=spawn_agent,
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

    @staticmethod
    def build_agent(
        profile: AgentProfile,
        *,
        name: str | None = None,
    ) -> Agent:
        """Construct an Agent from a saved profile.

        Args:
            profile: Source profile for model/instruction/inference settings.
            name: Override the Agent name (defaults to the profile name upcased).

        Raises:
            RuntimeError: If the profile has no model configured.
        """
        if not profile.provider or not profile.model:
            msg = f"Profile '{profile.id}' is not fully configured"
            raise RuntimeError(msg)

        raw_options: dict[str, Any] = {
            "num_ctx": profile.context_window,
            "num_predict": profile.num_predict,
            "temperature": profile.temperature,
            "top_k": profile.top_k,
            "top_p": profile.top_p,
            "repeat_penalty": profile.repeat_penalty,
            "reasoning_effort": profile.reasoning_effort,
            "reasoning_summary": profile.reasoning_summary,
            "thinking_budget": profile.thinking_budget,
        }
        options = {k: v for k, v in raw_options.items() if v is not None}

        return Agent(
            name=name or profile.name.upper(),
            description=profile.description,
            instruction=profile.system_prompt,
            provider=profile.provider,
            model=profile.model,
            think=profile.think or False,
            options=options,
            context_window=profile.context_window or 0,
            compaction_threshold=profile.compaction_threshold or 0.75,
            max_iterations=profile.max_iterations or 0,
        )


def _base_tools(
    *, allow_spawn: bool, allow_load_skills: bool, spawn_agent: Callable[..., Any]
) -> list[Callable[..., Any]]:
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

        tools += [spawn_agent, list_agent_profiles]
    if allow_load_skills:
        from skills._tools import list_available_skills, load_skill

        tools += [load_skill, list_available_skills]
    return tools


async def _restore_persisted_loaded_skills(
    agent_capabilities: AgentCapabilities,
    skill_ids: Iterable[str],
) -> None:
    """Resolve and restore the conversation's dynamically loaded skills."""
    from skills._policy import is_reserved_skill_id
    from skills._resolve import resolve_skill

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
