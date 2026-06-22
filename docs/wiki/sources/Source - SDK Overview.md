---
title: "Source - SDK Overview"
type: source
tags: [sdk, agent-loop, providers, hooks, context, events, skills, turn]
created: 2026-06-22
updated: 2026-06-22
sources: []
---

# Source - SDK Overview

## Summary

The `sdk/` package is the core agent infrastructure that everything else builds on. It exposes the [[Agent Loop]] via `run_turn`, the [[Hook System]] via typed hook classes, the [[Context Management]] system via `ContextManager` and `ConversationHistory`, a [[Provider Abstraction]] layer supporting Ollama/OpenAI/Anthropic/OpenRouter/Fake, an event system via `EventDispatcher` and `publish_event`, and the [[Skill System]] via `AgentState` and `Skill` models. The turn lifecycle (enter/exit, stop signaling, nudge queues) is managed by `turn_scope`.

## Key Points

- `run_turn(history, agent, hooks)` is the main entry point — drives the LLM → tool call → result loop
- `turn_scope()` is an async context manager that sets up EventDispatcher, stop events, conversation ID tracking, and tears them all down cleanly after the turn
- The Provider protocol defines `chat()`, `chat_stream()`, `list_models()`, `invalidate_model_cache()`
- Providers are loaded lazily, cached by name, and resolved via either a `direct_providers` base_url or a Unix Domain Socket broker
- Five concrete providers: `OllamaProvider`, `OpenAIResponsesProvider` (native Responses API), `OpenAIProvider` (compat), `AnthropicProvider`, `FakeProvider` (testing)
- Hook phases: `on_turn_start`, `before_model`, `after_model`, `before_tool`, `after_tool`, `on_turn_end`
- Shipped hooks: `BudgetGuard`, `ContextHook`, `LoadedSkillHook`, `LoggingHook`, `LoopDetector`, `NudgeHook`, `PersistenceHook`, `ScratchpadHook`, `StopHook`, `ToolResultCapHook`
- `default_hooks()` builds the standard hook chain from an agent config
- `ContextManager` holds `ConversationHistory` + `AgentState`; publishes `ContextUsagePayload` events; runs pluggable `ContextStrategy` objects
- `LLMCompactionStrategy` triggers at a configured fill ratio, summarizes old messages via an LLM, keeps recent groups verbatim
- `AgentState` tracks base tools + dynamically loaded skills; `loaded_skill_ids` is the cross-turn delta
- `Skill` model: id, name, description, prompt fragment, list of tool callables
- Event system uses `ContextVar`-stored `EventDispatcher`; `publish_event()` works without passing dispatcher through call stack
- `agent_span()` sets the current agent context for attribution in events
- All event payload types are discriminated unions on `type` field

## Entities Mentioned

- [[AgentLoop]]
- [[EventDispatcher]]
- [[ContextManager]]
- [[ConversationHistory]]
- [[LLMCompactionStrategy]]
- [[AgentState]]
- [[Skill]]
- [[OllamaProvider]]
- [[AnthropicProvider]]
- [[OpenAIProvider]]
- [[OpenAIResponsesProvider]]
- [[FakeProvider]]
- [[BudgetGuard]]
- [[ContextHook]]
- [[LoggingHook]]
- [[LoopDetector]]
- [[PersistenceHook]]
- [[StopHook]]
- [[run_turn]]
- [[turn_scope]]
- [[callable_to_json_schema]]

## Concepts Covered

- [[Agent Loop]]
- [[Turn Lifecycle]]
- [[Hook System]]
- [[Provider Abstraction]]
- [[Context Compaction]]
- [[Skill System]]
- [[Event System]]

## Raw Notes

- `_active_agent_state` ContextVar is set inside `agent_span()` so `run_turn` can access it without parameter passing
- Parallel tool execution controlled by `config.parallel.enabled` and `config.parallel.max_concurrent`
- Retry logic: 5 attempts with exponential backoff; mid-stream failures fall back to non-streaming `chat()` to avoid content duplication
- `check_stop()` is called between tool calls — clean interruption without task cancellation
- `MOCK_LLM=1` env var routes all providers to `FakeProvider` for e2e testing
