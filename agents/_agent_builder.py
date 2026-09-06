"""Build Agent instances from AgentProfile configs."""

import logging
from collections.abc import Callable
from typing import Any

from agents._agent_profiles import AgentProfile
from agents.types import Agent

logger = logging.getLogger(__name__)

_OPTION_CONTROLS = {
    "num_ctx": "context_window",
    "num_predict": "num_predict",
    "temperature": "temperature",
    "top_k": "top_k",
    "top_p": "top_p",
    "repeat_penalty": "repeat_penalty",
    "reasoning_effort": "reasoning_effort",
    "reasoning_summary": "reasoning_summary",
    "thinking_budget": "thinking_budget",
}


def build_agent(
    profile: AgentProfile,
    tools: list[Callable[..., Any]],
    *,
    name: str | None = None,
) -> Agent:
    """Construct an Agent from a profile and tool list.

    Args:
        profile: Source profile for model/instruction/inference settings.
        tools: Tool callables the agent can invoke.
        name: Override the Agent name (defaults to the profile name upcased).

    Raises:
        RuntimeError: If the profile has no model configured.
    """
    if not profile.provider or not profile.model:
        msg = f"Profile '{profile.id}' is not fully configured"
        raise RuntimeError(msg)

    raw_options: dict[str, Any] = {
        # num_ctx is an Ollama runtime option. Cloud/gateway models have a
        # fixed model context; profile.context_window is still retained below
        # as OmniDeck's local compaction denominator.
        "num_ctx": profile.context_window if profile.provider == "ollama" else None,
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
        tools=tools,
        provider=profile.provider,
        model=profile.model,
        think=profile.think or False,
        options=options,
        context_window=profile.context_window or 0,
        compaction_threshold=profile.compaction_threshold or 0.75,
        max_iterations=profile.max_iterations or 0,
    )


async def resolve_agent_runtime_metadata(agent: Agent) -> Agent:
    """Apply live model capabilities without persisting cloud metadata.

    A profile stores user choices. Fixed cloud context capacity and accepted
    inference parameters belong to the selected model, so they are resolved
    on every run through the provider's cached model catalog.
    """
    try:
        from sdk.providers import get_provider

        provider = get_provider(agent.provider)
        models = await provider.list_models()
        model_info = next((candidate for candidate in models if candidate.name == agent.model), None)
    except Exception:
        logger.warning(
            "Could not resolve runtime metadata for %s/%s; using profile fallbacks",
            getattr(agent, "provider", "unknown"),
            getattr(agent, "model", "unknown"),
            exc_info=True,
        )
        return agent
    if model_info is None:
        logger.warning("Model metadata not found for %s/%s", agent.provider, agent.model)
        return agent

    context_window = agent.context_window
    if model_info.context_window and (
        agent.provider != "ollama" or model_info.is_cloud or context_window <= 0
    ):
        context_window = model_info.context_window

    options = dict(agent.options)
    if model_info.inference_controls is not None:
        supported = set(model_info.inference_controls)
        options = {
            key: value
            for key, value in options.items()
            if _OPTION_CONTROLS.get(key) in supported
        }
    if (
        model_info.thinking_levels
        and isinstance(options.get("reasoning_effort"), str)
        and options["reasoning_effort"] not in model_info.thinking_levels
    ):
        options.pop("reasoning_effort")

    return agent.model_copy(update={
        "context_window": context_window,
        "options": options,
        "think": model_info.thinking_required or (
            agent.think and model_info.supports_thinking
        ),
    })


__all__ = ["build_agent", "resolve_agent_runtime_metadata"]
