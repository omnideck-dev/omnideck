---
title: Hooks System
type: concept
tags: [sdk, hooks, turn, extensibility]
created: 2026-07-07
updated: 2026-07-07
verified_commit: 6a5625d
paths:
  - "sdk/hooks/"
---

# Hooks System

## Overview

Hooks are pluggable callbacks that observe and can modify the agent turn loop without touching the core execution logic. They let higher-level concerns (persistence, context management, logging, safety limits) compose onto the loop independently.

## How It Works

Each hook is an object implementing any subset of these phases (all optional):

| Phase | Called when | Can modify |
|-------|-------------|-----------|
| `on_turn_start(agent_name)` | Before any LLM work | — |
| `before_model(history, iteration, agent_name)` | Before each LLM call | history (in-place) |
| `after_model(response, history, iteration, agent_name)` | After each LLM call | response (return new one) |
| `before_tool(tool_name, arguments)` | Before each tool execution | arguments / intercept |
| `after_tool(tool_name, arguments, result)` | After each tool execution | result (return new one) |
| `on_turn_end(final_content, agent_name)` | After the turn (always runs) | — |

Hooks are constructed fresh per turn and composed in order by `default_hooks()`. The turn loop calls each applicable phase on every hook in sequence.

## Standard Hooks

| Hook | File | Purpose |
|------|------|---------|
| `NudgeHook` | `_nudge_hook.py` | Splices queued nudge messages into history before model calls |
| `StopHook` | `_stop_hook.py` | Checks per-conversation stop event; raises `StopRequestedError` |
| `BudgetGuard` | `_budget_guard.py` | Enforces `max_iterations`; raises after limit |
| `LoopDetector` | `_loop_detector.py` | Detects repetitive tool-call sequences; injects a warning message |
| `LoggingHook` | `_logging_hook.py` | Rich console panels for each turn (visible in `just logs`) |
| `ScratchpadHook` | `_scratchpad_hook.py` | Manages agent scratchpad tool state |
| `LoadedSkillHook` | `_loaded_skill_hook.py` | Appends the loaded-skills XML block to the system message before each call |
| `ToolResultCapHook` | `_result_cap.py` | Truncates oversized tool results to prevent context overflow |
| `ContextHook` | `_context_hook.py` | Calls `ContextManager.maybe_compact()` before each model call |
| `PersistenceHook` | `_persistence.py` | Saves `ConversationHistory` to disk after each model call |
| `AgentEventBufferHook` | `_agent_event_buffer.py` | Buffers events for post-turn persistence to `events.json` |

## Where It Lives

| Path | Role |
|------|------|
| `sdk/hooks/` | All hook implementations |
| `sdk/hooks/_default.py` | `default_hooks()` factory |
| `sdk/turn/_execution.py` | Phase dispatch loop |

## Key Details

- `PersistenceHook` saves after each **model call** (not just at turn end) so a crash mid-turn doesn't lose everything. History is reloaded from disk on the next turn if the process restarts.
- `LoopDetector` compares recent tool call sequences against a sliding window. When it detects a repeat, it appends a system-level nudge ("you seem to be repeating yourself") to break the cycle.
- Adding a new hook: implement the relevant phase methods, add an instance to the `hooks` list in `server/message_handler.py:_run_turn()`, or extend `default_hooks()` if it belongs in every turn.

## Open Questions

- Hook ordering is currently fixed in `default_hooks()`. There is no priority or dependency mechanism for custom hooks.

## Sources

- `docs/sdk_semantics.md` — Hook phases and lifecycle
