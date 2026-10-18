---
title: Turn Lifecycle
type: concept
tags: [sdk, agent, turn, hooks, streaming]
created: 2026-07-07
updated: 2026-07-07
verified_commit: 6a5625d
paths:
  - "sdk/turn/"
  - "server/message_handler.py"
  - "sdk/hooks/"
---

# Turn Lifecycle

## Overview

A **turn** is a single user message → agent response cycle. It encompasses all LLM calls, tool executions, sub-agent work, and event emissions needed to produce one reply. Turns within a conversation execute sequentially; there is no parallel execution of turns within a single conversation.

## How It Works

### 1. HTTP Request Arrives

`POST /api/chat` → `server/aiohttp_app.py:chat_handler()` validates the request with Pydantic and calls `server/message_handler.py:handle_user_message()`.

### 2. Conversation Lookup

`handle_user_message()` resolves or creates a `ConversationHistory` via an LRU in-memory cache (capped at 25 entries, hydrated from disk on miss).

### 3. Agent Construction

The `AgentProfile` is loaded by ID → `build_agent()` constructs an `Agent` dataclass carrying the model name, system prompt, inference options, and tool list.

### 4. Turn Scope

`turn_scope(conversation_id)` opens an async context that:
- Creates a fresh `EventDispatcher` bound via ContextVar to the turn
- Installs a per-conversation stop event (for cooperative cancellation)
- Opens a nudge queue (for mid-turn user interrupts)
- Marks the conversation as active (prevents LRU eviction)

### 5. Agent Span

`agent_span(agent_name, instruction, ...)` opens a context tracking the root agent's execution depth. Sub-agents spawned during the turn get deeper spans. The span automatically emits `AgentStartedPayload` on entry and `AgentCompletedPayload` on exit.

### 6. Hook Composition

`default_hooks()` assembles the standard hook chain:
1. `NudgeHook` — injects queued nudge messages before model calls
2. `StopHook` — checks for stop requests at each iteration
3. `BudgetGuard` — enforces `max_iterations` limit
4. `LoopDetector` — detects repetitive tool-call patterns
5. `LoggingHook` — Rich console output per turn
6. `ScratchpadHook` — manages the agent's scratchpad tool
7. `LoadedSkillHook` — appends the loaded-skills block to every model call
8. `ToolResultCapHook` — truncates oversized tool results to fit the context window
9. `ContextHook` — fires compaction strategies when context approaches capacity
10. `PersistenceHook` — saves conversation history to disk after each model call

### 7. `run_turn()` Loop

`sdk/turn/run_turn()` drives the agent:
1. Call `before_model(history, iteration)` on all hooks
2. Call the LLM provider with current history + tools
3. Call `after_model(response, ...)` on hooks (can rewrite)
4. If the response contains tool calls: call `before_tool`, execute, call `after_tool` for each
5. Append results to history; repeat from 1
6. When the model stops calling tools (or stop/budget fires): call `on_turn_end()`

### 8. Event Streaming

Tools and the turn loop publish events via `publish_event()`. The `EventDispatcher` fans them out to all subscribers. `handle_user_message()` bridges the dispatcher into an `asyncio.Queue` and yields events to the `stream_events()` SSE writer, which serializes each event as a JSONL line.

### 9. Post-Turn Work

After the turn loop completes:
- `AgentEventBufferHook` saves the turn's events (screenshots, file outputs, terminal blocks) to `events.json` for conversation resume
- Loaded skill IDs are persisted to conversation metadata
- For new conversations, a background task generates a title via LLM

## Where It Lives

| File | Role |
|------|------|
| `server/message_handler.py` | HTTP-to-agent bridge, LRU conversation cache |
| `sdk/turn/_turn.py` | `run_turn()` core loop |
| `sdk/turn/_execution.py` | Hook dispatch phases |
| `sdk/turn/_scope.py` | `turn_scope()` context manager |
| `sdk/hooks/_default.py` | `default_hooks()` factory |
| `sdk/events/_context.py` | `agent_span()`, `publish_event()` |
| `sdk/events/_dispatcher.py` | `EventDispatcher` |

## Key Details

- **Conversation isolation:** each `conversation_id` has its own history, context manager, and stop event. Concurrent conversations don't share state.
- **Stop signal:** `request_stop(conversation_id)` sets a ContextVar event that `StopHook` checks before each LLM call. Raises `StopRequestedError` which is caught cleanly by `_run_turn()`.
- **Nudge:** `queue_nudge(agent_id, text)` injects a user message into a running turn without creating a new turn. The `NudgeHook` splices it into history before the next model call.
- **Sub-agents:** the turn loop calls tools synchronously, but a `spawn_agent` tool can recursively invoke `run_turn()` for a sub-agent inside the same turn scope. Sub-agents inherit the parent's dispatcher and stop event.

## Open Questions

- Parallel sub-agent execution — currently sub-agents are sequential; the config has `parallel.enabled` but it's not yet wired.

## Sources

- `docs/sdk_semantics.md` — authoritative description of Turn, Conversation, Agent Span, Event
