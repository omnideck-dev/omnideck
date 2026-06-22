---
title: AgentLoop
type: entity
tags: [agent, loop, turn, tool-call, execution]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - SDK Overview]]", "[[Source - Server Overview]]"]
---

# AgentLoop

## Overview

`AgentLoop` is the core `run_turn()` function in `sdk/turn/_execution.py`. It implements the ReAct pattern: iteratively call the LLM, execute any tool calls, add results to history, and repeat until the model returns without tool calls (or a stop condition triggers). This loop is the runtime engine that processes every user message.

## Details

**Entry point:** `sdk.turn.run_turn(history, agent, hooks=None)`

**Loop mechanics:**
1. Call `before_model` hooks
2. Stream tokens from the provider via `_stream_chat_with_retries`; publish `ContentPayload` delta events
3. Call `after_model` hooks (can rewrite the response)
4. Append assistant message to history
5. If no tool calls: return final content
6. For each tool call: call `before_tool` hooks, execute tool, call `after_tool` hooks, append result to history
7. Optionally execute tool calls in parallel (controlled by `config.parallel`)
8. Repeat

**Iteration tracking:** `iteration` counter increments each loop; passed to hooks for budget/loop-detection

**Stop handling:** `check_stop()` is called in the streaming delta loop; raises `StopRequestedError` which exits cleanly with partial content saved

**Parallel tool execution:** controlled by `ParallelConfig.enabled` and `max_concurrent`; uses `asyncio.Semaphore`

**Error handling:** `ProviderError` messages surfaced to user; other exceptions wrapped in `ToolLoopError`

**On-turn-end:** all hooks receive `on_turn_end(final_content, agent_name)` in the `finally` block

**Key dependency:** `_active_agent_state` ContextVar must be set (done by `agent_span()`) before `run_turn` is called; raises `ToolLoopError` otherwise

## Related Entities

- [[run_turn]] (the function itself)
- [[turn_scope]] (lifecycle context manager)
- [[Agent]] (configuration the loop uses)
- [[ConversationHistory]] (mutated in place by the loop)
- [[AgentState]] (provides the active tool list)
- [[EventDispatcher]] (receives published events)
- [[Hook System]] concept
- [[OllamaProvider]], [[AnthropicProvider]], [[OpenAIProvider]] (called by the loop)
- [[callable_to_json_schema]] (used to describe tools to providers)

## Sources

- [[Source - SDK Overview]]
- [[Source - Server Overview]]
