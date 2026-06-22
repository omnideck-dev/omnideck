---
title: AnthropicProvider
type: entity
tags: [provider, anthropic, claude, llm]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - SDK Overview]]"]
---

# AnthropicProvider

## Overview

`AnthropicProvider` (in `sdk/providers/_anthropic.py`) is the LLM provider backed by the Anthropic Messages API. It supports both direct API key authentication and proxied routing via a Unix Domain Socket (for brokered key management). It implements the `Provider` protocol.

## Details

**Proxy mode:** when `proxy_socket` is provided, routes all SDK traffic through a UDS using `httpx.AsyncHTTPTransport`; uses "http://localhost" as base_url with api_key="proxy"

**Direct mode:** uses `api_key` and optional `base_url` directly

**Message conversion:** converts internal message format (OpenAI-like) to Anthropic's format:
- `system` role messages extracted as separate `system` parameter
- `assistant` messages with tool_calls → `tool_use` content blocks
- `tool` role messages → `user` messages with `tool_result` content blocks
- User messages with images → multi-part content blocks

**Tool conversion:** converts Python callables to Anthropic's `{name, description, input_schema}` format via `callable_to_json_schema`

**Thinking:** `think=True` sets `thinking: {type: "enabled", budget_tokens: N}` and forces `temperature=1`; three budget levels: minimal (1024), standard (max_tokens // 2), extended (max_tokens)

**Prompt caching:** always appends `cache_control: {type: "ephemeral"}` for automatic Anthropic prompt caching (90% token discount on cache hits)

**Model cache:** 5-minute TTL; `list_models()` paginates the Anthropic models API (limit=100)

**Image support detection:** Claude 3+ and Claude 4 models support images; detected by model ID prefix matching

**Thinking support detection:** claude-3-7-sonnet and claude-4 models; detected by model ID prefix

**Error wrapping:** `ProviderError` with `retryable=True` for HTTP 408, 429, 5xx, 529

**Stop reason mapping:** `end_turn` → "stop", `tool_use` → "tool_calls", `max_tokens` → "length"

## Related Entities

- [[Provider]] protocol
- [[OpenAIProvider]]
- [[OllamaProvider]]
- [[OpenAIResponsesProvider]]
- [[BrokerClient]] (used in proxy mode)
- [[callable_to_json_schema]]

## Sources

- [[Source - SDK Overview]]
