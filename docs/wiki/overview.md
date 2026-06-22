---
title: Wiki Overview
type: overview
created: 2026-06-22
updated: 2026-06-22
---

# Wiki Overview

## What Is Omnideck

Omnideck (internal codename: Computron 9000) is a self-hosted agentic workbench that runs as a single container. Users bring their own LLM providers (cloud: OpenAI, Anthropic, OpenRouter, or any OpenAI-compatible endpoint; local: Ollama) and connect integrations (Gmail, Calendar, Drive, custom MCP servers). The agent can browse the web with a real browser, write and execute code, remember facts across conversations, run autonomous background tasks, and work with external services — all on user hardware.

The system is installed and managed by a separate Go CLI (`omnideck`), which wraps Docker/Podman and provides guided install, update, and health-check commands.

## Architecture at a Glance

```
Container
  aiohttp server (:8080)
    agents/        — profile registry + agent builder
    sdk/           — agent loop, providers, hooks, context, events, skills
    server/        — HTTP API + React UI
    tools/         — browser, virtual_computer, memory, web, generation
    integrations/  — supervisor/broker credential isolation
    conversations/ — conversation persistence
    tasks/         — autonomous background task engine
    config/        — static YAML config
    settings.py    — mutable runtime settings (JSON)
  Desktop (Xfce + VNC + noVNC)
  GPU inference models

Host
  Ollama (LLM inference via --network=host)
  Docker/Podman (container runtime)
```

## Current Wiki State

The wiki was created on 2026-06-22 from a full source exploration. Coverage is substantive across all major subsystems.

**Well-documented areas:**
- Agent loop mechanics (`run_turn`, tool-call cycle, retry, parallel execution)
- Turn lifecycle (`turn_scope`, ContextVars, stop signaling, event routing)
- Hook system (all shipped hooks documented with their phases and behavior)
- Provider abstraction (all five providers documented with their specific behaviors)
- Context compaction (full algorithm, serialization rules, VRAM management)
- Skill system (baseline vs. runtime-loaded, cross-turn persistence)
- Browser automation (two modes, guard rails, screenshot events)
- Integration supervisor/broker pattern (credential isolation, LLM proxying)
- Config vs settings distinction (AppConfig immutable; settings.py mutable)
- Event system (publisher, dispatcher, ContextVar routing, JSONL streaming)

**Partially documented (open questions noted):**
- Execution policy (`tools/virtual_computer/_policy.py` deny patterns not fully read)
- Integration broker details (full list of supported brokers not confirmed)
- Vault encryption mechanism not explored
- `spawn_agent` tool internals not fully read (`sdk/tools/_spawn_agent.py`)
- Sub-agent parallelism behavior not fully confirmed
- `events.json` append vs rewrite behavior
- `preview_state.json` exact schema

**Not yet covered:**
- Desktop agent (`tools/desktop/`) — Xfce + VNC integration
- Generation tools (`tools/generation/`) — image/music/video (feature-flagged)
- Custom tools (`tools/custom_tools/`) — user-defined tools
- Scratchpad (`tools/scratchpad/`)
- `sdk/skills/default_skills/` — what default skills are shipped
- React UI source (`server/ui/`) — frontend architecture
- Migration system (`migrations/`)
- Test suite (`tests/`)

## Key Design Decisions

1. **ContextVars for implicit context** — EventDispatcher, stop events, agent identity, and conversation ID flow implicitly through the async call stack without parameter threading
2. **Hooks as duck-typed protocol** — no base class; hooks just implement methods matching phase names
3. **Provider registry with lazy loading** — provider SDKs (heavy) only imported when first used
4. **Credential isolation via supervisor** — app server never holds decrypted credentials
5. **Profiles are snapshots** — baseline skills re-derived each turn so profile edits take effect immediately
6. **Atomic writes everywhere** — memory.json, settings.json, and all conversation files use tempfile+rename
7. **LRU conversation cache** — disk is authoritative; in-memory cache is evictable; active turns are eviction-protected
