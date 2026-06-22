---
title: OpenAIProvider
type: entity
tags: [provider, openai, openrouter, openai-compat, llm]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - SDK Overview]]"]
---

# OpenAIProvider

## Overview

`OpenAIProvider` (in `sdk/providers/_openai.py`) implements the `Provider` protocol for OpenAI-compatible APIs. This includes `openai_compat` (any OpenAI-compatible endpoint) and `openrouter`. It uses the OpenAI Python SDK and can be directed to any base URL.

## Details

**Handles:** `openai_compat` and `openrouter` provider names (both route to this class)

**Configuration:** `base_url` from `settings.direct_providers[name]["base_url"]`; or proxy socket for brokered providers

**Proxy mode:** routes via UDS using `httpx.AsyncHTTPTransport` (same pattern as [[AnthropicProvider]])

**Tool support:** converts Python callables to OpenAI function-call format via `callable_to_json_schema`

**Model cache:** `list_models()` returns models from the OpenAI models endpoint

**Related class:** `OpenAIResponsesProvider` (in `_openai_responses.py`) — uses the native OpenAI Responses API (newer, streaming-first format); registered as provider name `"openai"`

## Related Entities

- [[Provider]] protocol
- [[AnthropicProvider]]
- [[OllamaProvider]]
- [[OpenAIResponsesProvider]]
- [[callable_to_json_schema]]
- [[BrokerClient]] (proxy mode)

## Sources

- [[Source - SDK Overview]]
