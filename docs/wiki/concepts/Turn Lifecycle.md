---
title: Turn Lifecycle
type: concept
tags: [turn, lifecycle, context-var, stop, nudge, events]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - SDK Overview]]", "[[Source - Server Overview]]"]
---

# Turn Lifecycle

## Overview

A "turn" in Omnideck is one complete user message → assistant response cycle, including all tool calls and sub-agent work. The turn lifecycle governs how the system is set up and torn down around each turn, ensuring clean isolation between turns, proper event routing, and safe stop/interrupt handling.

## How It Works

```
handle_user_message()
    └─ turn_scope(handler, conversation_id)    ← async context manager
        ├─ Create EventDispatcher
        ├─ Create asyncio stop event
        ├─ Register conversation as active
        ├─ Set ContextVars (dispatcher, stop_event, conversation_id)
        ├─ Subscribe handler (event queue writer)
        │
        └─ [body: agent_span → run_turn]
        
        On exit (normal or exception):
        ├─ Publish TurnEndPayload
        ├─ drain() EventDispatcher (wait for in-flight async handlers)
        ├─ Unsubscribe handler
        ├─ Reset ContextVars
        ├─ Remove conversation from active set
        └─ Remove stop event
```

**ContextVars set during turn:**
- `_current_dispatcher` — `EventDispatcher` instance; `publish_event()` uses this
- `_stop_event` — `asyncio.Event`; `check_stop()` reads this
- `_conversation_id` — conversation ID string; `get_conversation_id()` reads this

**Stop signaling:**
- `request_stop(conversation_id)` — HTTP endpoint sets the stop event for a specific conversation
- `check_stop()` — raises `StopRequestedError` at safe checkpoints (within streaming delta loop)
- Stop is per-conversation: stopping one conversation doesn't affect others

**Nudge queues:**
- Mid-turn user messages sent via `/api/nudge`
- `queue_nudge(agent_id, text)` queues a message
- `NudgeHook` (if loaded) drains the queue at `before_model` phase and injects messages into history

**Sub-agent inheritance:** ContextVars are inherited by child asyncio tasks; sub-agents spawned within a turn automatically publish to the same dispatcher and inherit the same stop event

## Key Details

- `is_turn_active(conversation_id)` allows external code (e.g., LRU eviction) to check before making changes
- `any_turn_active()` used for monitoring
- `drain()` is called before teardown to ensure all async event handlers complete before the queue consumer stops
- `TurnEndPayload` is published inside the `finally` block — always fires even if the body raises

## Sources

- [[Source - SDK Overview]]
- [[Source - Server Overview]]
