---
title: EventDispatcher
type: entity
tags: [events, dispatcher, pub-sub, asyncio]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - SDK Overview]]"]
---

# EventDispatcher

## Overview

`EventDispatcher` (in `sdk/events/_dispatcher.py`) is an asyncio-friendly publish/subscribe system for `AgentEvent` objects. Each turn gets a fresh dispatcher instance stored in a ContextVar so `publish_event()` works from any call depth without explicit parameter threading.

## Details

**Interface:**
- `subscribe(handler)` — adds a handler; no-op if already subscribed
- `unsubscribe(handler)` — removes handler
- `publish(event)` — fans out to all subscribers; async handlers scheduled as tasks, sync handlers as `call_soon`
- `drain()` — waits for all in-flight async tasks to complete (used at turn end)
- `subscription(handler)` — async context manager that auto-unsubscribes
- `reset()` — clears all subscribers (test isolation)

**Handler scheduling:**
- Async handlers: `asyncio.create_task()` — non-blocking
- Sync handlers: `loop.call_soon()` — deferred to event loop
- Errors in handlers are logged but not re-raised (defensive)

**Task tracking:** `_tasks: set[asyncio.Task]` tracks in-flight async tasks; tasks self-remove via `done_callback`

**Drain semantics:** snapshot of tasks at drain time; new tasks published during drain are not awaited

**ContextVar storage:** `_current_dispatcher: ContextVar[EventDispatcher | None]` is set by `turn_scope()` and inherited by sub-agents automatically via Python's ContextVar semantics

**Access:** `get_current_dispatcher()` and `publish_event()` helpers in `sdk/events/_context.py`

## Related Entities

- [[AgentEvent]] (the event type being dispatched)
- [[turn_scope]] (creates and binds the dispatcher)
- [[agent_span]] (enriches events with attribution)
- [[MessageHandler]] (subscribes `_queue_handler` as a handler)

## Sources

- [[Source - SDK Overview]]
