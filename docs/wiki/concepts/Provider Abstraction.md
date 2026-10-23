---
title: Provider Abstraction
type: concept
tags: [providers, agent-core, llm]
created: 2026-10-18
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "agent_core/providers/"
  - "providers/"
---

# Provider Abstraction

## Overview

Omnideck supports Ollama (local), OpenAI, Anthropic, OpenRouter, or any
OpenAI-compatible endpoint, with per-role model assignment — chat, vision, and
compaction can each use a different provider/model. Two packages split the concern:
`agent_core/providers/` defines the protocol and normalized types every provider
implements; top-level `providers/` is the application layer that resolves a provider
*name* (a string like `"ollama"`) to a live instance, handling direct-vs-brokered
connection and test-mode faking.

## How It Works

### The protocol

`agent_core/providers/_protocol.py`'s `Provider` is a `Protocol` (structural typing, no
inheritance required): `from_config(llm_config)`, `chat(...)`, `chat_stream(...)`,
`list_models()`, `invalidate_model_cache()`. `_models.py` defines the normalized types
every provider speaks regardless of its upstream API: `ChatMessage`, `ChatResponse`,
`ChatDelta`, `ToolCall`/`ToolCallFunction`, `TokenUsage`, `ModelInfo`, and `ProviderError`
(carries `retryable`/`status_code` so callers can decide whether to retry — see the
retry loop in [[Turn Lifecycle]]).

`_base.py`'s `BaseAPIProvider` is a shared base for API-key providers (OpenAI,
Anthropic) — `chat_stream()` falls back to calling `chat()` once and yielding the whole
response if a provider hasn't implemented true streaming.

Concrete implementations: `_ollama.py` (`OllamaProvider`), `_openai.py` (`OpenAIProvider`
— used for both `openai_compat` and `openrouter`), `_openai_responses.py`
(`OpenAIResponsesProvider` — the actual `openai` provider, using OpenAI's Responses API
rather than Chat Completions), `_anthropic.py` (`AnthropicProvider`).

### Resolving a provider by name

`providers/__init__.py`'s `get_provider(provider_name)` is the one entry point
application code calls. It:
1. Returns a cached instance if one exists (`_provider_cache`).
2. If `MOCK_LLM` is set in the environment, always returns the in-process
   `providers._fake.FakeProvider` regardless of the requested name — this is what lets
   the e2e suite run without any real LLM backend (see `_fake.py`'s directive-protocol
   docstring for the scripting language e2e tests use: `<<SAY>>`, `<<TOOL>>`,
   `<<MODEL>>`, `<<SPAWN>>`, `<<PARALLEL>>`, `<<FAIL>>`, `<<PROVIDERFAIL>>`, `<<SLOW>>`).
3. Otherwise instantiates via `_create_provider()`:
   - **Direct providers** (Ollama, no-auth OpenAI-compatible endpoints) connect straight
     to a `base_url` from `settings.direct_providers`.
   - **Everything else** is a **brokered** connection: the provider is constructed with
     a `proxy_socket` pointing at a Unix socket (`llm_{provider}.sock` under
     `config.integrations.sockets_dir`) reached through the brokering subsystem — model
     traffic for credentialed providers goes through the same broker-process pattern as
     tool integrations (see [[Integrations Architecture]]), not a direct HTTPS call
     from the app process.
   - A provider configured as neither raises a `ValueError` pointing at the Providers
     settings page.
4. `reset_provider(provider_name=None)` clears one or all cached instances (used after a
   settings change so the next call picks up new config).

### Per-role model assignment

Settings (`settings.json`, read via `load_settings()`) carry separate
provider/model/options for chat, vision (`vision_provider`/`vision_model`), and
compaction (`compaction_provider`/`compaction_model`) — see [[Context Compaction]] for
how the compaction role is used and `providers/_vision.py`'s `vision_generate()` for the
vision role. `AgentProfile.provider`/`.model` set the chat role per-profile; vision and
compaction are global settings, not per-profile.

## Where It Lives

| File | Role |
|------|------|
| `agent_core/providers/_protocol.py` | `Provider` protocol |
| `agent_core/providers/_models.py` | Normalized request/response types |
| `agent_core/providers/_base.py` | `BaseAPIProvider` shared base |
| `agent_core/providers/_ollama.py`, `_openai.py`, `_openai_responses.py`, `_anthropic.py` | Concrete providers |
| `providers/__init__.py` | `get_provider()`, `reset_provider()` — name → instance resolution |
| `providers/_fake.py` | `FakeProvider` — deterministic, directive-scripted, used under `MOCK_LLM` |
| `providers/_vision.py` | `vision_generate()` — routes an image prompt through the configured vision provider |

## Key Details

- **`agent_core/providers/` vs. top-level `providers/` is a real split, not a
  duplicate.** The former is the portable protocol/implementation layer; the latter is
  Omnideck's own provider-name resolution policy (direct vs. brokered, caching, test
  faking). Don't conflate them when reading imports.
- **Brokering, not direct connection, is the default for credentialed providers.** Only
  Ollama and no-auth OpenAI-compatible endpoints connect directly from the app process.
- **`MOCK_LLM` overrides the provider name entirely** — even a request for `"anthropic"`
  gets `FakeProvider` when the env var is set, which is how e2e tests get fully
  deterministic, scripted model behavior without network access.

## Open Questions

- The exact shape of what lives in `agent_core/providers/_runtime_stats.py`
  (`LLMRuntimeStats`) vs. `ChatResponse.usage` — appears to be Ollama-specific
  timing/throughput metadata read from `response.raw`, not used by every provider.

## Sources

- None beyond source code for this pass.
