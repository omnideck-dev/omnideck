---
title: Event System
type: concept
tags: [sdk, events, streaming, sse, ui]
created: 2026-07-07
updated: 2026-07-07
verified_commit: 6a5625d
paths:
  - "sdk/events/"
  - "server/aiohttp_app.py"
---

# Event System

## Overview

The event system is the mechanism by which agent activity — text output, tool calls, browser screenshots, file outputs, terminal commands, generation progress — flows from the backend to the React UI in real time. It uses a ContextVar-scoped `EventDispatcher` that fans events out to subscribers, bridged over Server-Sent Events (SSE) as JSONL.

## How It Works

### Event Types

All events are instances of `AgentEvent`, a thin envelope wrapping one `AgentEventPayload`. Payloads are a discriminated union on the `type` field:

| Payload type | When emitted |
|---|---|
| `content` | LLM text delta or complete chunk (with optional `thinking`) |
| `turn_end` | Root agent finished responding |
| `tool_call` | Before a tool executes |
| `browser_screenshot` | After a browser action captures the viewport |
| `file_output` | When a file is produced in the virtual computer |
| `terminal_output` | Bash command start/end in the virtual computer |
| `context_usage` | After each LLM call — token counts and fill ratio |
| `agent_started` | An agent span begins (root or sub-agent) |
| `agent_completed` | An agent span ends |
| `spawn_requested` | The `spawn_agent` tool begins spawning a sub-agent |
| `generation_preview` | Image/video generation progress |
| `audio_playback` | Agent wants to play audio in the browser |
| `desktop_active` | Desktop environment started |
| `tool_created` | A new custom tool was created |

### Publishing

Tools and the turn loop call `publish_event(payload)` from `sdk/events/_context.py`. The function:
1. Reads the current `AgentEvent` context (dispatcher + agent span) from ContextVars
2. Wraps the payload in an `AgentEvent` envelope with `agent_name`, `agent_id`, and `depth`
3. Calls `dispatcher.dispatch(event)` which delivers to all registered subscribers

### Dispatch

`EventDispatcher` (`sdk/events/_dispatcher.py`) maintains a list of async subscriber callables. Subscribers are per-turn — a new dispatcher is created for each turn inside `turn_scope()`. Multiple subscribers can be active simultaneously (e.g., the SSE bridge and the `AgentEventBufferHook` that saves events for conversation resume).

### SSE Bridge

In `server/message_handler.py:handle_user_message()`, a subscriber bridges the dispatcher to an `asyncio.Queue`. The queue is drained by `stream_events()` in `server/aiohttp_app.py`, which serializes each event as `model_dump(mode="json") + "\n"` and writes it to the HTTP response stream.

The frontend reads the SSE stream in `useStreamingChat.js` and dispatches each event to the React agent reducer.

### Agent Span Attribution

Every published event automatically carries the emitting agent's `agent_name`, `agent_id` (a hierarchical dot-notation ID like `root.browser_agent.1`), and `depth` (0 = root, 1+ = sub-agents). This lets the UI route events to the correct agent card in the network view without the tool code knowing anything about the UI layout.

## Where It Lives

| File | Role |
|------|------|
| `sdk/events/_models.py` | `AgentEvent` + all payload types |
| `sdk/events/_dispatcher.py` | `EventDispatcher` |
| `sdk/events/_context.py` | `agent_span()`, `publish_event()`, ContextVar management |
| `sdk/events/__init__.py` | Re-exports for consumers |
| `server/aiohttp_app.py:stream_events()` | SSE serialization |
| `server/ui/src/hooks/useStreamingChat.js` | Frontend SSE consumer |

## Key Details

- **JSONL format:** each event is one JSON object per line, flushed immediately. The UI can render partial output as it arrives.
- **`exclude_none=True, exclude_defaults=True`** in serialization keeps the wire format lean — fields that weren't set don't appear.
- **`AgentEventBufferHook`** accumulates events during the turn and saves them to `events.json` after the turn completes, so the preview panel (browser tabs, terminal output, file blocks) can be restored when a conversation is resumed.
- **Disconnection handling:** `ConnectionResetError` during stream write is caught silently — the agent turn continues even if the user closes the browser tab.

## Open Questions

- There is no backpressure from the SSE stream back to the agent loop. A very fast agent could theoretically fill the queue unboundedly on a slow client.

## Sources

- `docs/sdk_semantics.md` — canonical description of Event concept
