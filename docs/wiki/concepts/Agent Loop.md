---
title: Agent Loop
type: concept
tags: [agent, loop, react, tool-call, iteration]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - SDK Overview]]", "[[Source - Server Overview]]"]
---

# Agent Loop

## Overview

The Agent Loop is the core runtime cycle that processes a user message: call the LLM, execute any requested tools, feed results back, and repeat until the model produces a final response without tool calls. It is the Omnideck implementation of the ReAct (Reasoning + Acting) pattern.

## How It Works

```
User message → history
     ↓
[before_model hooks]
     ↓
Provider.chat_stream() → stream token deltas → publish ContentPayload events
     ↓
[after_model hooks] → may rewrite response
     ↓
No tool calls? → return final_content
     ↓
For each tool call:
  [before_tool hook] → may intercept
  Execute tool → result
  [after_tool hook] → may transform result
  Append tool result to history
     ↓
Loop back to before_model hooks
```

**Termination conditions:**
- Model returns with no tool calls → normal completion
- `StopRequestedError` raised → user-requested stop (partial content saved)
- `max_iterations` exceeded → forced stop via `BudgetGuard` hook
- `ToolLoopError` raised → unhandled exception

**Parallel execution:** if `config.parallel.enabled`, multiple tool calls from one model response execute concurrently via `asyncio.gather` with a semaphore.

## Key Details

- `run_turn()` drives the loop; each iteration is tracked by an `iteration` counter passed to hooks
- All history mutation is in-place: `history.append()` for each assistant message and tool result
- `check_stop()` called after each streaming delta — allows clean interruption without cancelling tasks
- On retry (provider failure), falls back to non-streaming `chat()` to avoid content duplication
- The loop reads `_active_agent_state` ContextVar (set by `agent_span`) for the live tool list

## Open Questions

- Does the loop support branching (multiple sub-agents in parallel)? The spawn_agent tool creates sub-agents but they run as sequential calls within a turn — TODO: verify parallelism behavior with spawn_agent

## Sources

- [[Source - SDK Overview]]
- [[Source - Server Overview]]
