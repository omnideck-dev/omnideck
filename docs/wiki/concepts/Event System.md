---
title: Event System
type: concept
tags: [agent-core, events, sse, persistence]
created: 2026-07-07
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "agent_core/events/"
  - "agent_core/context/_history.py"
  - "agent_runtime/_session.py"
  - "conversations/"
---

# Event System

## Overview

Events are the single source of truth for a conversation. `AgentEvent` objects aren't
transient UI notifications layered on top of some other state — they *are* the state.
`ConversationHistory` (the LLM-facing message list), the on-disk `events.jsonl` log, and
the UI's live stream are all different views over the same append-only sequence of
events. This event-sourced design replaced an earlier mutable-message-list model (the
previous wiki described `ConversationHistory` as "an in-memory ordered list of LLM
messages" persisted as `history.json` — that's no longer accurate; see
[[ConversationHistory]], which a different pass of this regeneration should reconcile
with `agent_core/context/_history.py`).

## How It Works

### Payload types

`agent_core/events/_models.py` defines one Pydantic model per event kind, joined into a
discriminated union `AgentEventPayload` on a `type` field. As of this page's
`verified_commit`, the union has 18 members, including: `ContentPayload` (streamed
text/thinking), `IterationPayload` (one full model iteration — thinking + content + tool
calls), `ToolResultPayload`, `UserMessagePayload` (opening message or mid-turn nudge),
`AgentStartedPayload`/`AgentCompletedPayload` (agent-span lifecycle), `SpawnRequestedPayload`
(sub-agent spawn correlation), `CompactionPayload` (see [[Context Compaction]]),
`ContextUsagePayload`, `BrowserScreenshotPayload`, `FileOutputPayload`,
`TerminalOutputPayload`, `GenerationPreviewPayload`, `AudioPlaybackPayload`,
`DesktopActivePayload`, `ToolCreatedPayload`, `ErrorPayload`, and `TurnEndPayload`.

`AgentEvent` is the thin envelope: a stable `id`, UTC `timestamp`, `agent_name`/`agent_id`/
`depth` attribution, and one payload. `to_flat_dict()` merges envelope + payload into the
flat one-line-JSON shape written to `events.jsonl`.

### Publishing

`agent_core.events.publish_event(event)` (`_context.py`) is the only way code emits an
event. It reads a `ContextVar`-bound stack of `(context_id, agent_name)` frames to fill
in `agent_name`/`agent_id`/`depth` automatically, then calls `add_event()` on whatever
`EventSink` is bound to the current coroutine context via `set_current_conversation()`.
If nothing is bound (e.g. a unit test with no turn running), it's a silent no-op.

`agent_span(agent_name, instruction, ...)` is an async context manager that pushes a
frame onto that stack and publishes the matching `AgentStartedPayload` /
`AgentCompletedPayload` pair around whatever runs inside it — this is what gives every
event its agent attribution and nesting depth.

### The sink: `ConversationHistory`

`agent_core/context/_history.py`'s `ConversationHistory` implements `EventSink`:
`add_event()` appends the event to an in-memory list (for retained types — see
`_RETAINED_EVENT_TYPES`) and synchronously fans it out to subscribed observers. Reading
`.messages` doesn't return a stored list — it calls `build_llm_view()` (`_view.py`) to
derive the LLM-shaped message array from the event log on demand, scoped to a specific
`agent_id` for sub-agent threads.

### Observers (fan-out)

`RunSession.__aenter__` (`agent_runtime/_session.py`) subscribes several observers to
the history before a run starts:
- `EventsLogWriter` — appends each event to `events.jsonl` on disk
- `BrowserTabsWriter`, `TerminalWriter`, `ArtifactsIndexWriter` — maintain derived
  per-conversation indexes (open tabs, terminal blocks, generated files)
- `RunSession._record` — assigns a run-scoped sequence number for SSE replay (see
  [[Turn Lifecycle]])

Observers can be sync or async; async ones run as tracked `asyncio.Task`s that
`drain_observers()` waits on before the run's resources close.

### Reaching the UI

The UI consumes events over the chat run's SSE stream, reading `RunHandle.events()`
from the owning `RunSession`'s sequence-numbered buffer, which supports reconnect/replay
without gaps or duplicates.

## Where It Lives

| File | Role |
|------|------|
| `agent_core/events/_models.py` | Payload types, `AgentEvent` envelope |
| `agent_core/events/_context.py` | `publish_event()`, `agent_span()`, context-stack accessors |
| `agent_core/context/_history.py` | `ConversationHistory` — the canonical `EventSink` |
| `agent_core/context/_view.py` | `build_llm_view()` — derives the LLM message list from events |
| `agent_runtime/_session.py` | Wires disk/UI observers onto the history for a run |
| `conversations/` | `EventsLogWriter` and friends — disk persistence of the event log |

## Key Details

- **Events are derived from, not accompanying, the message history.** There is no
  separate "append a message" API — publish an event and the next read of `.messages`
  reflects it.
- **Retained vs. full log:** the in-memory copy on `ConversationHistory` only keeps
  types in `_RETAINED_EVENT_TYPES` (enough to rebuild the LLM view and support warm UI
  resume); the full event stream — including UI-only events like screenshots — still
  reaches disk writers and the SSE bridge via the observer fan-out, it just isn't kept
  in the in-memory list.
- **Sub-agent scoping:** a child `ConversationHistory` is constructed with
  `agent_id=<execution_id>`; `build_llm_view()` filters to just that agent's events so a
  sub-agent's model calls never see the parent's (or siblings') history.
- **Attribution is automatic, not passed explicitly.** Any code that calls
  `publish_event()` inside an `agent_span()` gets correct `agent_name`/`agent_id`/`depth`
  for free — this is why tool implementations never need to know which agent is running
  them.

## Open Questions

- None identified this pass.

## Sources

- None beyond source code for this pass.
