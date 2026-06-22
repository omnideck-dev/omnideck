---
title: Event System
type: concept
tags: [events, pub-sub, dispatcher, streaming, sse, context-var]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - SDK Overview]]", "[[Source - Server Overview]]"]
---

# Event System

## Overview

The Event System is how Omnideck communicates from deep inside the agent loop back to the HTTP response stream and the browser UI. It uses a ContextVar-stored `EventDispatcher` so any code can publish events without receiving a dispatcher handle as a parameter. Events flow as JSONL via chunked HTTP responses.

## How It Works

**Publishing (anywhere in the call stack):**
```python
from sdk.events import publish_event, AgentEvent, ContentPayload

publish_event(AgentEvent(payload=ContentPayload(
    type="content",
    content="Hello!",
    delta=True,
)))
```
`publish_event` reads `_current_dispatcher` ContextVar and calls `dispatcher.publish(event)`.

**Subscription (in `turn_scope`):**
```python
async with turn_scope(handler=my_handler, conversation_id=...):
    ...
```
`my_handler(event: AgentEvent)` is called for every published event.

**Routing to HTTP (in `message_handler`):**
```python
async def _queue_handler(evt: AgentEvent) -> None:
    await queue.put(evt)
```
An asyncio `Queue` bridges the event system to the HTTP streaming response.

**HTTP streaming (`stream_events`):**
- `StreamResponse` with `Transfer-Encoding: chunked`
- Each event: `event.model_dump(mode="json", exclude_none=True, exclude_defaults=True)` → JSON string + `\n`
- JSONL format: one JSON object per line
- `TurnEndPayload` signals the client to close the stream

**Agent attribution (`agent_span`):**
- `async with agent_span(name, instruction, agent_state, profile_name):` 
- Sets ContextVars: `_current_agent_name`, `_current_agent_id`, `_current_depth`
- Publishes `AgentStartedPayload` on enter, `AgentCompletedPayload` on exit
- All events published within the span are enriched with `agent_name`, `agent_id`, `depth` by `publish_event`

**Sub-agent inheritance:** ContextVars propagate to child asyncio tasks; sub-agents automatically publish to the parent turn's dispatcher

## Key Details

- `EventDispatcher.drain()` called at `turn_scope` exit ensures all async handlers complete before teardown
- Sync handlers run via `loop.call_soon` — deferred but not truly async
- Handler errors are logged but NOT propagated to the publisher
- `AgentEventBufferHook` subscribes as a handler to buffer lifecycle events for persistence (file outputs, screenshots)

## Sources

- [[Source - SDK Overview]]
- [[Source - Server Overview]]
