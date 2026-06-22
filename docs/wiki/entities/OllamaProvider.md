---
title: OllamaProvider
type: entity
tags: [provider, ollama, local-models, llm]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - SDK Overview]]", "[[Source - README.md]]"]
---

# OllamaProvider

## Overview

`OllamaProvider` (in `sdk/providers/_ollama.py`) implements the `Provider` protocol for the Ollama inference server. Ollama runs on the host machine and is accessed over the network (not via broker). It is configured as a "direct" provider with a base_url in `settings.direct_providers`.

## Details

**Configuration:** uses `base_url` from `settings.direct_providers["ollama"]["base_url"]`

**Supported features:** streaming, tool calls, optional thinking (depends on model), image input (depends on model)

**Model unloading:** after context compaction, `_unload_model(model)` shells out to `ollama stop {model}` to free VRAM — unique to local deployment

**Model listing:** `list_models()` queries Ollama's API to enumerate pulled models; cloud variants (e.g., `kimi-k2.5:cloud`) appear alongside local models after `ollama pull`

**Context for local deployment:**
- Ollama runs on host, not inside container
- Accessed at `localhost:11434` (Linux) or `host.docker.internal:11434` (macOS/Docker)
- Must be reachable via `--network=host` container flag
- On macOS/Docker Desktop, Ollama must bind to `0.0.0.0` (set `OLLAMA_HOST=0.0.0.0`)

## Related Entities

- [[Provider]] protocol
- [[AnthropicProvider]]
- [[OpenAIProvider]]
- [[LLMCompactionStrategy]] (unloads models after compaction)
- [[AppConfig]] (network configuration)

## Sources

- [[Source - SDK Overview]]
- [[Source - README.md]]
