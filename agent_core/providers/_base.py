"""Base class for API-key-based LLM providers (OpenAI, Anthropic, etc.)."""

from collections.abc import AsyncGenerator, Callable
from typing import Any, ClassVar

from ._model_metadata import listed_model
from ._models import ChatDelta, ChatResponse, LLMConfig, ModelInfo

# Returns the details another provider listed for one model, or None.
ModelDetails = Callable[[str], ModelInfo | None]


class BaseAPIProvider:
    """Shared base for providers that authenticate via API key.

    Subclass this for providers like OpenAI or Anthropic. Override
    ``chat()`` and ``list_models()`` when implementing the provider.
    """

    # The request format this adapter speaks. None for a provider that picks
    # a format per model.
    inference_api: ClassVar[str | None] = None

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        model_details: ModelDetails | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        # A provider that sends requests through this adapter passes its own
        # listing here, so requests use the details that provider listed.
        self._model_details = model_details
        self._model_cache: list[ModelInfo] | None = None

    def _listed_model(self, model: str) -> ModelInfo:
        """Return the model details requests to *model* follow."""
        if self._model_details is not None:
            listed = self._model_details(model)
            if listed is not None:
                return listed
        if self.inference_api is None:
            raise NotImplementedError(f"{type(self).__name__} has no single request format")
        return listed_model(self._model_cache, model, self.inference_api)

    @classmethod
    def from_config(cls, llm_config: LLMConfig) -> "BaseAPIProvider":
        """Construct from a direct-provider config (no API key — that path is brokered)."""
        return cls(base_url=llm_config.base_url)

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[Callable[..., Any]] | None = None,
        options: dict[str, Any] | None = None,
        think: bool = False,
    ) -> ChatResponse:
        raise NotImplementedError(f"{type(self).__name__} is not yet implemented")

    async def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[Callable[..., Any]] | None = None,
        options: dict[str, Any] | None = None,
        think: bool = False,
    ) -> AsyncGenerator[ChatDelta | ChatResponse, None]:
        """Default fallback: call chat() and yield the complete response."""
        yield await self.chat(
            model=model, messages=messages, tools=tools, options=options, think=think,
        )

    async def list_models(self) -> list[ModelInfo]:
        raise NotImplementedError(f"{type(self).__name__} is not yet implemented")

    def invalidate_model_cache(self) -> None:
        """Clear the model cache. Subclasses that cache should override this."""
