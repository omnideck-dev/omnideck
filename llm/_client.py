"""The interface every model client implements."""

from collections.abc import AsyncGenerator, Callable
from typing import Any, Protocol

from ._types import ChatDelta, ChatResponse, ModelInfo


class ModelClient(Protocol):
    """Talks to one provider in one request format."""

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[Callable[..., Any]] | None = None,
        options: dict[str, Any] | None = None,
        think: bool = False,
        model_info: ModelInfo | None = None,
    ) -> ChatResponse:
        """Send a chat completion request and return a normalized response."""
        ...

    def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[Callable[..., Any]] | None = None,
        options: dict[str, Any] | None = None,
        think: bool = False,
        model_info: ModelInfo | None = None,
    ) -> AsyncGenerator[ChatDelta | ChatResponse, None]:
        """Stream token deltas followed by a final ChatResponse."""
        ...

    async def list_models(self) -> list[ModelInfo]:
        """Return available models with metadata."""
        ...

    def invalidate_model_cache(self) -> None:
        """Clear cached model metadata."""
        ...
