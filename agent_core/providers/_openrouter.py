"""OpenRouter's OpenAI-compatible transport with explicit usage semantics."""

from typing import Any

from ._models import TokenUsage
from ._openai import OpenAIProvider


class OpenRouterProvider(OpenAIProvider):
    """OpenRouter reports cache writes and account charges with each completion."""

    @staticmethod
    def _extract_usage(usage: Any) -> TokenUsage:
        result = OpenAIProvider._extract_usage(usage)
        # Credits are USD-denominated. Use the account charge, NOT
        # cost_details.upstream_inference_cost (which has different BYOK semantics).
        # https://openrouter.ai/docs/cookbook/administration/usage-accounting
        # https://openrouter.ai/support
        cost = getattr(usage, "cost", None)
        return TokenUsage.model_validate({**result.model_dump(), "reported_cost_usd": cost})
