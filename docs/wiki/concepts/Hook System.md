---
title: Hook System
type: concept
tags: [hooks, extensibility, turn-phases, before-model, after-model]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - SDK Overview]]"]
---

# Hook System

## Overview

The Hook System is the extensibility mechanism for the agent loop. Hooks are plain Python objects with optional methods matching specific phase names. They are called by `run_turn()` at defined points in the turn lifecycle. Hooks can observe, modify, or intercept behavior at each phase.

## How It Works

**Phase signatures:**

| Phase | Signature | Description |
|-------|-----------|-------------|
| `on_turn_start` | `(agent_name) -> None` | Called once at the start of a turn |
| `before_model` | `async (history, iteration, agent_name) -> None` | Before each LLM call |
| `after_model` | `async (response, history, iteration, agent_name) -> ChatResponse` | After each LLM call; can rewrite response |
| `before_tool` | `(tool_name, tool_arguments) -> str | None` | Before tool execution; return non-None to intercept |
| `after_tool` | `(tool_name, tool_arguments, tool_result) -> str` | After tool execution; can rewrite result |
| `on_turn_end` | `(final_content, agent_name) -> None` | Called in `finally` block; always fires |

**Hook chaining:** hooks are a list; all are called in order. `before_tool` stops after the first non-None return (interception). `after_model` chains the response through all hooks (each receives the possibly-modified response from the previous).

**Duck typing:** no base class required; a hook only needs to implement the phases it cares about. `getattr(hook, "before_model", None)` is used to check for each method.

## Key Details

**Shipped hooks:**

| Hook | Purpose |
|------|---------|
| `BudgetGuard` | Forces stop after `max_iterations` |
| `ContextHook` | Calls `ctx_manager.before_model()` and `ctx_manager.after_model()` |
| `LoadedSkillHook` | Injects skill prompt section into system message before model call |
| `LoggingHook` | Logs tool calls and turn start/end |
| `LoopDetector` | Detects repeated identical tool calls and nudges the model |
| `NudgeHook` | Drains nudge queue and injects mid-turn user messages |
| `PersistenceHook` | Saves conversation history at `on_turn_end` |
| `ScratchpadHook` | Manages a scratchpad for agent reasoning |
| `StopHook` | Checks `check_stop()` at `before_model` |
| `ToolResultCapHook` | Truncates excessively long tool results |
| `AgentEventBufferHook` | Buffers lifecycle events for persistence |

**`default_hooks(agent, max_iterations, ctx_manager)`:** builds the standard list; `PersistenceHook` is added separately in `message_handler`

## Open Questions

- Can hooks communicate with each other? Currently no shared state mechanism — hooks are independent. TODO: investigate if there's any hook-to-hook data passing.

## Sources

- [[Source - SDK Overview]]
