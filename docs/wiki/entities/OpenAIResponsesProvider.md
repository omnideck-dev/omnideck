---
title: OpenAIResponsesProvider
type: entity
tags: [provider, openai, responses-api, llm]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - SDK Overview]]"]
---

# OpenAIResponsesProvider

## Overview

`OpenAIResponsesProvider` (in `sdk/providers/_openai_responses.py`) implements the `Provider` protocol using OpenAI's native Responses API (as opposed to the Chat Completions API used by [[OpenAIProvider]]). It is registered under the provider name `"openai"`.

## Details

**API difference from OpenAIProvider:** Uses the Responses API endpoint which is the newer, streaming-first OpenAI API. Different request/response format from Chat Completions.

**Provider name:** `"openai"` in `_PROVIDER_PATHS`

**Proxy/direct modes:** same pattern as other providers — UDS proxy or direct base_url

## Related Entities

- [[Provider]] protocol
- [[OpenAIProvider]] (Chat Completions-based variant)
- [[AnthropicProvider]]

## Sources

- [[Source - SDK Overview]]
