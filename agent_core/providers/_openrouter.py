"""OpenRouter chat transport with cache boundaries for routed Claude models."""

from collections.abc import Callable
from typing import Any

from ._openai import OpenAIProvider
from ._prompt_cache import cache_conversation


class OpenRouterProvider(OpenAIProvider):
    """Keep routing-specific cache controls out of generic compatible endpoints."""

    def _build_kwargs(
        self, model: str, messages: list[dict[str, Any]], tools: list[Callable[..., Any]] | None,
        options: dict[str, Any] | None, think: bool = False,
    ) -> dict[str, Any]:
        kwargs = super()._build_kwargs(model, messages, tools, options, think)
        if model.startswith("anthropic/"):
            cache_conversation(kwargs["messages"])
        return kwargs
