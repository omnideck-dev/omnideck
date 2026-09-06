"""Provider contracts and implementations independent of application configuration."""

from ._models import ChatDelta, ChatMessage, ChatResponse, LLMConfig, ModelInfo, ProviderError, TokenUsage, ToolCall, ToolCallFunction
from ._protocol import Provider
from ._role_defaults import resolve_model_info, resolve_role_options
from ._runtime_stats import LLMRuntimeStats, llm_runtime_stats

__all__ = [
    "ChatDelta", "ChatMessage", "ChatResponse", "LLMConfig", "ModelInfo",
    "Provider", "ProviderError", "TokenUsage", "ToolCall", "ToolCallFunction",
    "LLMRuntimeStats", "llm_runtime_stats", "resolve_model_info",
    "resolve_role_options",
]
