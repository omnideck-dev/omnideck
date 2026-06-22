---
title: Provider Abstraction
type: concept
tags: [provider, llm, protocol, abstraction, openai, anthropic, ollama]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - SDK Overview]]"]
---

# Provider Abstraction

## Overview

The Provider Abstraction layer allows Omnideck to work with multiple LLM backends through a single `Provider` protocol. Concrete implementations normalize different API formats into a common `ChatResponse`/`ChatDelta` interface, and the provider registry manages caching and resolution.

## How It Works

**The Provider Protocol (`sdk/providers/_protocol.py`):**
```python
class Provider(Protocol):
    @classmethod
    def from_config(cls, llm_config: LLMConfig) -> Provider: ...
    async def chat(*, model, messages, tools, options, think) -> ChatResponse: ...
    def chat_stream(*, model, messages, tools, options, think) -> AsyncGenerator[ChatDelta | ChatResponse, None]: ...
    async def list_models() -> list[ModelInfo]: ...
    def invalidate_model_cache() -> None: ...
```

**Normalized types:**
- `ChatResponse` — message content, thinking, tool_calls, token usage, done_reason, raw response
- `ChatDelta` — incremental content or thinking text for streaming
- `ChatMessage` — content + optional thinking + optional tool_calls
- `TokenUsage` — prompt_tokens, completion_tokens, cache_read_tokens, cache_creation_tokens
- `ModelInfo` — name, context_window, max_output_tokens, supports_images, supports_thinking

**Provider resolution:**
1. `get_provider(name)` checks cache first
2. If `MOCK_LLM=1` env: always returns `FakeProvider`
3. Check `settings.direct_providers[name].base_url` — if set, use direct connection
4. Check `{sockets_dir}/llm_{name}.sock` — if exists, use proxy mode (broker)
5. Neither configured → raises `ValueError` with setup instruction

**Provider registry:**
```python
_PROVIDER_PATHS = {
    "ollama": "sdk.providers._ollama:OllamaProvider",
    "openai": "sdk.providers._openai_responses:OpenAIResponsesProvider",
    "openai_compat": "sdk.providers._openai:OpenAIProvider",
    "openrouter": "sdk.providers._openai:OpenAIProvider",
    "anthropic": "sdk.providers._anthropic:AnthropicProvider",
    "fake": "sdk.providers._fake:FakeProvider",
}
```

**Proxy mode:** brokered providers (API keys in vault) connect via Unix Domain Socket; the provider SDK routes HTTP through the broker; the broker adds auth headers before forwarding to the real API

## Key Details

- Provider classes are lazily loaded (importlib) to avoid importing heavy SDKs at startup
- Cache is module-level dict; `reset_provider(name)` clears it (e.g., after settings change)
- All providers return the same `ChatResponse` shape; consumers don't need provider-specific code
- `think=True` parameter enables extended thinking on supporting models (Anthropic Claude 3.7+/4+, some Ollama models)

## Sources

- [[Source - SDK Overview]]
