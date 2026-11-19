"""Talk to LLM providers: shared types, model details, and request rules.

The clients themselves live in ``llm.clients`` so that importing these types
does not load any provider SDK.
"""

from ._client import ModelClient
from ._model_lookup import find_model
from ._model_metadata import accepted_options, build_model_info, with_output_cap
from ._runtime_stats import LLMRuntimeStats, llm_runtime_stats
from ._types import (
    ChatDelta,
    ChatMessage,
    ChatResponse,
    ModelInfo,
    ProviderError,
    TokenUsage,
    ToolCall,
    ToolCallFunction,
)

__all__ = [
    "ChatDelta",
    "ChatMessage",
    "ChatResponse",
    "LLMRuntimeStats",
    "ModelClient",
    "ModelInfo",
    "ProviderError",
    "TokenUsage",
    "ToolCall",
    "ToolCallFunction",
    "accepted_options",
    "build_model_info",
    "find_model",
    "llm_runtime_stats",
    "with_output_cap",
]
