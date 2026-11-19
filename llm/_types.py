"""Types shared by every model client and its callers.

Each client turns its service's native responses into these types, so
callers never handle service-specific objects.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProviderError(Exception):
    """Error raised by an LLM provider with retryability information.

    Attributes:
        retryable: Whether the caller should retry the request.
        status_code: HTTP status code if applicable.
    """

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        if cause is not None:
            self.__cause__ = cause


class ToolCallFunction(BaseModel):
    """Normalized function within a tool call."""

    name: str
    arguments: dict[str, Any]


class ToolCall(BaseModel):
    """A single tool invocation requested by the model."""

    id: str | None = None
    function: ToolCallFunction


class ChatMessage(BaseModel):
    """Provider-agnostic assistant message from a chat completion."""

    content: str | None = None
    thinking: str | None = None
    tool_calls: list[ToolCall] | None = None


class TokenUsage(BaseModel):
    """Normalized token counts."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


class ChatDelta(BaseModel):
    """A single incremental token fragment from a streaming chat response."""

    content: str | None = None
    thinking: str | None = None


class ChatResponse(BaseModel):
    """Normalized response from any provider's chat endpoint."""

    message: ChatMessage
    usage: TokenUsage = Field(default_factory=TokenUsage)
    done_reason: str | None = None
    raw: Any = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ModelInfo(BaseModel):
    """Metadata for an available model, returned by a client's list_models()."""

    name: str
    display_name: str | None = None
    context_window: int | None = None
    max_output_tokens: int | None = None
    supports_images: bool = False
    supports_thinking: bool = False
    parameter_size: str | None = None
    quantization_level: str | None = None
    family: str | None = None
    wire_api: str | None = None
    # The request format and the request settings this model accepts.
    # ``wire_api`` is only a readable label for that format.
    inference_api: str | None = None
    inference_controls: list[str] | None = None
    # How a thinking level is sent, which levels the model accepts, and the
    # level it uses when none is chosen. None means thinking cannot be set.
    thinking_control: str | None = None
    thinking_levels: list[str] | None = None
    thinking_default: str | None = None
    thinking_required: bool = False
    # Controls the request format rejects while thinking is on, and groups of
    # controls the model rejects when more than one of them is set.
    thinking_excluded_controls: list[str] | None = None
    exclusive_controls: list[list[str]] | None = None
    capabilities: list[str] = Field(default_factory=list)
    is_cloud: bool = False
