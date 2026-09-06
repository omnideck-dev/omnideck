"""Anthropic provider implementation."""

import inspect
import json
import logging
import time
from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from typing import Any

from ._base import BaseAPIProvider
from ._model_metadata import (
    discovered_metadata,
    fallback_metadata,
    inference_controls,
    metadata_value,
    thinking_configuration,
    thinking_default,
)
from ._models import ChatDelta, ChatMessage, ChatResponse, ModelInfo, ProviderError, TokenUsage, ToolCall, ToolCallFunction
from sdk.tools import callable_to_json_schema

logger = logging.getLogger(__name__)

_REQUIRED_MESSAGE_ARGUMENTS = {"model", "messages", "max_tokens"}

_MODEL_CACHE_TTL = 300.0  # 5 minutes

# Anthropic stop reason → normalized done_reason
_STOP_REASON_MAP: dict[str, str] = {
    "end_turn": "stop",
    "tool_use": "tool_calls",
    "max_tokens": "length",
    "stop_sequence": "stop",
}


class AnthropicProvider(BaseAPIProvider):
    """LLM provider backed by the Anthropic Messages API."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        proxy_socket: Path | None = None,
        send_authorization: bool = True,
    ) -> None:
        super().__init__(api_key, base_url)
        import anthropic

        if proxy_socket is not None:
            # Route all SDK traffic through the llm_proxy broker's UDS.
            # The Anthropic SDK adds /v1/messages paths relative to base_url;
            # using "http://localhost" means it sends to http://localhost/v1/...
            # which the proxy receives and forwards to the real upstream.
            import httpx
            transport = httpx.AsyncHTTPTransport(uds=str(proxy_socket))
            http_client = httpx.AsyncClient(transport=transport)
            self._client = anthropic.AsyncAnthropic(
                http_client=http_client,
                base_url="http://localhost",
                api_key="proxy",
            )
        else:
            client_class = anthropic.AsyncAnthropic
            if not send_authorization:

                class _NoAuthAsyncAnthropic(anthropic.AsyncAnthropic):
                    @property
                    def auth_headers(self) -> dict[str, str]:
                        return {}

                client_class = _NoAuthAsyncAnthropic
            kwargs: dict[str, Any] = {}
            if api_key and send_authorization:
                kwargs["api_key"] = api_key
            elif not send_authorization:
                # The SDK requires a credential even though this subclass
                # deliberately emits no credential header.
                kwargs["api_key"] = "not-required"
            if base_url:
                kwargs["base_url"] = base_url
            self._client = client_class(**kwargs)

        self._model_cache: list[ModelInfo] | None = None
        self._model_cache_at: float = 0.0

    def _build_kwargs(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[Callable[..., Any]] | None,
        options: dict[str, Any] | None,
        think: bool,
    ) -> dict[str, Any]:
        """Build kwargs dict for the Anthropic messages API."""
        opts = options or {}
        system_prompt, converted = _convert_messages(messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": converted,
            "max_tokens": opts.get("num_predict") or opts.get("max_tokens") or 16384,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if opts.get("temperature") is not None:
            kwargs["temperature"] = opts["temperature"]
        if opts.get("top_k") is not None:
            kwargs["top_k"] = opts["top_k"]
        if opts.get("top_p") is not None:
            kwargs["top_p"] = opts["top_p"]

        if tools:
            kwargs["tools"] = _convert_tools(tools)

        if think:
            kwargs["temperature"] = 1
            effort = opts.get("reasoning_effort")
            if effort:
                # Claude 4.6+ uses adaptive thinking. Effort is a soft depth
                # control and belongs in output_config, not thinking itself.
                kwargs["thinking"] = {"type": "adaptive"}
                kwargs["output_config"] = {"effort": effort}
            else:
                # Manual extended thinking requires budget_tokens >= 1024 and
                # strictly less than max_tokens.
                max_tok = max(kwargs["max_tokens"], 2048)
                kwargs["max_tokens"] = max_tok
                thinking_budget = opts.get("thinking_budget", "standard")
                budget_map = {
                    "minimal": 1024,
                    "standard": max_tok // 2,
                    "extended": max_tok - 1,
                }
                budget = budget_map.get(thinking_budget, max_tok // 2)
                kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": min(max_tok - 1, max(1024, budget)),
                }

        # Automatic prompt caching — Anthropic places a cache breakpoint at
        # the end of the cacheable prefix. Subsequent turns with the same
        # prefix read from cache at 90% discount.
        kwargs["cache_control"] = {"type": "ephemeral"}

        return kwargs

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[Callable[..., Any]] | None = None,
        options: dict[str, Any] | None = None,
        think: bool = False,
    ) -> ChatResponse:
        """Send a chat request via Anthropic and normalize the response."""
        kwargs = _supported_message_kwargs(
            self._client.messages.stream,
            self._build_kwargs(model, messages, tools, options, think),
        )

        try:
            async with self._client.messages.stream(**kwargs) as stream:
                response = await stream.get_final_message()
        except Exception as exc:
            raise _wrap_error(exc) from exc
        return _normalize_response(response)

    async def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[Callable[..., Any]] | None = None,
        options: dict[str, Any] | None = None,
        think: bool = False,
    ) -> AsyncGenerator[ChatDelta | ChatResponse, None]:
        """Stream token deltas followed by a final ChatResponse."""
        kwargs = _supported_message_kwargs(
            self._client.messages.stream,
            self._build_kwargs(model, messages, tools, options, think),
        )

        try:
            async with self._client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_delta":
                        if event.delta.type == "text_delta":
                            yield ChatDelta(content=event.delta.text)
                        elif event.delta.type == "thinking_delta":
                            yield ChatDelta(thinking=event.delta.thinking)
                response = await stream.get_final_message()
        except Exception as exc:
            raise _wrap_error(exc) from exc
        yield _normalize_response(response)

    async def list_models(self) -> list[ModelInfo]:
        """Return available Anthropic models with metadata, cached for 5 minutes."""
        now = time.monotonic()
        if self._model_cache is not None and now - self._model_cache_at < _MODEL_CACHE_TTL:
            return self._model_cache
        try:
            response = await self._client.models.list(limit=100)
            results: list[ModelInfo] = []
            for m in response.data:
                discovered = discovered_metadata(m)
                supports_images = bool(metadata_value(
                    m.id, "supports_images", discovered.get("supports_images"),
                ))
                supports_thinking = bool(metadata_value(
                    m.id, "supports_thinking", discovered.get("supports_thinking"),
                ))
                thinking_control, thinking_levels, thinking_required = thinking_configuration(
                    "anthropic_messages", m.id, supports_thinking,
                )
                if discovered.get("thinking_control"):
                    thinking_control = discovered["thinking_control"]
                if discovered.get("thinking_levels"):
                    thinking_levels = discovered["thinking_levels"]
                if "thinking_required" in discovered:
                    thinking_required = discovered["thinking_required"]
                results.append(ModelInfo(
                    name=m.id,
                    context_window=metadata_value(
                        m.id, "context_window", discovered.get("context_window"),
                    ),
                    max_output_tokens=metadata_value(
                        m.id, "max_output_tokens", discovered.get("max_output_tokens"),
                    ),
                    supports_images=supports_images,
                    supports_thinking=supports_thinking,
                    inference_api="anthropic_messages",
                    inference_controls=inference_controls(
                        "anthropic_messages",
                        supports_thinking,
                        thinking_control,
                        model_id=m.id,
                        supported_parameters=discovered.get("supported_parameters"),
                    ),
                    thinking_control=thinking_control,
                    thinking_levels=thinking_levels,
                    thinking_default=discovered.get("thinking_default") or thinking_default(
                        m.id, thinking_control, thinking_levels,
                    ),
                    thinking_required=thinking_required,
                ))
            self._model_cache = results
            self._model_cache_at = now
            return self._model_cache
        except Exception as exc:
            raise _wrap_error(exc) from exc

    def invalidate_model_cache(self) -> None:
        """Clear the cached model list so the next call re-fetches."""
        self._model_cache = None
        self._model_cache_at = 0.0


def _supported_message_kwargs(method: Callable[..., Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Keep request fields accepted by the installed Anthropic SDK client.

    Anthropic exposes different ``messages.stream`` signatures for direct and
    Bedrock clients, and those signatures have changed between SDK releases.
    Inspecting the bound method keeps optional sampling fields from failing a
    request before it reaches Aperture while retaining the required request
    envelope. Wrappers accepting ``**kwargs`` remain untouched.
    """
    try:
        parameters = inspect.signature(method).parameters.values()
    except (TypeError, ValueError):
        return kwargs
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters):
        return kwargs

    supported = {
        parameter.name
        for parameter in parameters
        if parameter.kind in {
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }
    }
    supported.update(_REQUIRED_MESSAGE_ARGUMENTS)
    filtered = {key: value for key, value in kwargs.items() if key in supported}
    dropped = kwargs.keys() - filtered.keys()
    if dropped:
        logger.debug(
            "Ignoring request options unsupported by %s: %s",
            type(getattr(method, "__self__", None)).__name__,
            ", ".join(sorted(dropped)),
        )
    return filtered


def _supports_images(model_id: str) -> bool:
    """Return the catalog fallback for Claude image input."""
    return bool(fallback_metadata(model_id).get("supports_images", False))


def _supports_thinking(model_id: str) -> bool:
    """Return the catalog fallback for Claude extended thinking."""
    return bool(fallback_metadata(model_id).get("supports_thinking", False))


def _convert_messages(
    messages: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Convert internal message format to Anthropic's format.

    Returns:
        Tuple of (system_prompt, messages).
    """
    system_prompt: str | None = None
    converted: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "")

        if role == "system":
            system_prompt = msg.get("content", "")
            continue

        if role == "assistant":
            content_blocks: list[dict[str, Any]] = []
            text = msg.get("content")
            if text:
                content_blocks.append({"type": "text", "text": text})
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                for tc in tool_calls:
                    func = tc.get("function", {})
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": func.get("name", ""),
                        "input": func.get("arguments", {}),
                    })
            if content_blocks:
                converted.append({"role": "assistant", "content": content_blocks})
            continue

        if role == "tool":
            converted.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id", ""),
                    "content": msg.get("content", ""),
                }],
            })
            continue

        # user messages
        images = msg.get("images")
        if images:
            user_content_blocks: list[dict[str, Any]] = []
            text = msg.get("content")
            if text:
                user_content_blocks.append({"type": "text", "text": text})
            for img in images:
                user_content_blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img.get("media_type", "image/png"),
                        "data": img["data"],
                    },
                })
            converted.append({"role": "user", "content": user_content_blocks})
        else:
            converted.append({"role": "user", "content": msg.get("content", "")})

    return system_prompt, converted


def _convert_tools(tools: list[Callable[..., Any]]) -> list[dict[str, Any]]:
    """Convert Python callables to Anthropic's tool format."""
    result: list[dict[str, Any]] = []
    for func in tools:
        schema = callable_to_json_schema(func)
        fn = schema.get("function", {})
        result.append({
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {}),
        })
    return result


_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504, 529}


def _extract_api_message(exc: Exception) -> str:
    """Pull the human-readable message out of an Anthropic API error."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        # Direct shape: body = {message: "..."}
        if body.get("message"):
            return body["message"]
        # Nested shape: body = {error: {type, message}}
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            msg = err["message"]
            err_type = err.get("type", "")
            if err_type:
                return f"{err_type}: {msg}"
            return msg
    return str(exc)


def _wrap_error(exc: Exception) -> ProviderError:
    """Convert an Anthropic SDK exception into a ProviderError."""
    import anthropic

    if isinstance(exc, anthropic.APIStatusError):
        retryable = exc.status_code in _RETRYABLE_STATUS_CODES
        msg = _extract_api_message(exc)
        return ProviderError(
            msg,
            retryable=retryable,
            status_code=exc.status_code,
            cause=exc,
        )
    if isinstance(exc, anthropic.APIConnectionError):
        return ProviderError(str(exc), retryable=True, cause=exc)
    return ProviderError(str(exc), retryable=False, cause=exc)


def _normalize_response(raw: Any) -> ChatResponse:
    """Convert an Anthropic Message to our normalized ChatResponse."""
    content_parts: list[str] = []
    thinking_parts: list[str] = []
    tool_calls: list[ToolCall] = []

    for block in raw.content:
        if block.type == "text":
            content_parts.append(block.text)
        elif block.type == "thinking":
            thinking_parts.append(block.thinking)
        elif block.type == "tool_use":
            args = block.input
            if isinstance(args, str):
                args = json.loads(args)
            tool_calls.append(ToolCall(
                id=block.id,
                function=ToolCallFunction(
                    name=block.name,
                    arguments=args,
                ),
            ))

    cache_read = getattr(raw.usage, "cache_read_input_tokens", 0) or 0
    cache_creation = getattr(raw.usage, "cache_creation_input_tokens", 0) or 0
    if cache_read or cache_creation:
        logger.debug(
            "cache tokens: read=%d creation=%d (prompt=%d, completion=%d)",
            cache_read, cache_creation, raw.usage.input_tokens, raw.usage.output_tokens,
        )

    return ChatResponse(
        message=ChatMessage(
            content="\n".join(content_parts) if content_parts else None,
            thinking="\n".join(thinking_parts) if thinking_parts else None,
            tool_calls=tool_calls or None,
        ),
        usage=TokenUsage(
            prompt_tokens=raw.usage.input_tokens,
            completion_tokens=raw.usage.output_tokens,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_creation,
        ),
        done_reason=_STOP_REASON_MAP.get(raw.stop_reason, raw.stop_reason),
        raw=raw,
    )
