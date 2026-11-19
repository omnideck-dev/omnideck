---
title: ConversationHistory
type: entity
tags: [agent-core, conversation, history, persistence, events]
created: 2026-07-07
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "agent_core/context/_history.py"
  - "agent_core/context/_view.py"
  - "conversations/"
---

# ConversationHistory

## Overview

`ConversationHistory` is a **view over an append-only event log**, not a stored list of
messages. Formerly (`sdk/context/_history.py`, now dead) it held an ordered list of
`{role, content}` dicts directly; the current implementation in
`agent_core/context/_history.py` instead holds the raw events for a conversation
(`_events`) and derives the LLM-shaped message list on demand by running
`build_llm_view()` over them. There is no `history.json` anymore — the event log
(`events.jsonl`, written by `conversations/_events_log.py`'s `EventsLogWriter`) is the
single source of truth, and `ConversationHistory` is one of several things built from
it (the others: the transcript view the UI renders, and the warm in-memory resume path).

The persistence and lifecycle code around that log lives in `conversations/`, covered
below alongside the in-memory view, since there's no separate entity page for it.

## Location

`agent_core/context/_history.py`. Derivation logic (`build_llm_view`, `events_for_agent`)
in `agent_core/context/_view.py`. Disk persistence and conversation-level metadata in
`conversations/`.

## Details

| Member | Purpose |
|--------|---------|
| `messages` | System message (if set) + `derived_messages`. The LLM-ready view. |
| `system_message` | The currently active system prompt, held separately from the event log because it's refreshed every turn from agent + skill state, not a recorded interaction. |
| `derived_messages` | Runs `build_llm_view(self._events, agent_filter=self._agent_id)` fresh on every read. |
| `scoped_events` | The events belonging to *this* history's thread (root or one sub-agent) — used by context compaction to find kept bounds. |
| `recorded_events` | Snapshot of the raw in-memory event log. |

Key methods:

- `seed_events(events)` — replace the in-memory log wholesale; used at construction/resume to hydrate from `events.jsonl` before live events start arriving.
- `add_event(event)` — the canonical write path: appends the event to `_events` if its type is in `_RETAINED_EVENT_TYPES`, then fans it out synchronously (sync observers) or via a tracked `asyncio.Task` (async observers) to every subscriber.
- `subscribe(handler)` / `unsubscribe(handler)` — attach/detach an observer (e.g. the disk writer, the SSE bridge). Idempotent.
- `drain_observers()` — await any in-flight async observer tasks; used at shutdown so detached writers don't outlive the conversation.
- `handle_event(event)` — a backwards-compatible alias for `add_event`, kept because older code subscribed it directly to a dispatcher.

`_RETAINED_EVENT_TYPES` (in-memory log) is a strict subset of what the disk writer
persists: it must hold every type the warm-resume path replays to rebuild the UI
(`file_output`, `spawn_requested` included), or a conversation resumed from the warm
cache would lose things a cold disk resume keeps.

Per-agent scoping: `agent_id=None` means the root view (depth-0 agent only); a sub-agent
gets its own `ConversationHistory` constructed with its own `agent_id`, and
`derived_messages`/`scoped_events` filter the shared event list down to that agent's
thread. All agents in one turn share the same underlying `_events` list through the
observer fan-out — only the *view* differs.

## Persistence and lifecycle (`conversations/`)

- **`conversations/_events_log.py`** — `EventsLogWriter` subscribes to a conversation
  and appends each event as one JSON line to `events.jsonl`. A narrower
  `_PERSISTED_TYPES` set than the in-memory retention list — e.g. `context_usage` and
  `error` are persisted but not kept in the live in-memory view.
- **`conversations/_conversation_store.py`** — `ConversationStore` is the process-wide
  cache: an `OrderedDict[str, ConversationScope]` capped at `max_cached=25`, evicted
  LRU-first (skipping any conversation currently leased). `acquire()` is an async
  context manager that leases a conversation for the duration of a run and triggers
  eviction/cleanup via `ConversationScope.resources` (an `AsyncExitStack`) when the
  last lease releases — this is where browser sessions and other per-conversation
  resources get closed. `transient=True` scopes (e.g. one-off task-engine runs) are
  evicted as soon as their lease count hits zero rather than staying warm.
- **`conversations/_store.py`** — per-conversation `metadata.json` (title, pinned,
  folder, loaded skills, selected profile, preview-panel state) plus conversation
  listing/archiving/deletion. A conversation is recognized by the presence of
  `events.jsonl` inside its directory; archived conversations move intact into a
  reserved `_archived` sibling folder.
- **`conversations/_browser_tabs.py`**, **`conversations/_terminal.py`** — bounded,
  overwrite-in-place sidecars (`browser_tabs.json`, `terminal.json`) for UI panel state
  that would otherwise bloat the append-only log (screenshots were >90% of old logs
  before this split).
- **`conversations/_folders.py`** — a separate flat `_folders.json` registry for
  user-created sidebar folders; conversations reference a folder by id in their own
  metadata, nothing moves on disk when filed.
- **`conversations/_title_generation.py`** — generates a short LLM title from the first
  user message, using whatever model/provider is configured as the title model in
  [[Settings]] (falls back to a truncated first message if unconfigured or on error).

## Related Entities

- [[Context Compaction]] — reads `scoped_events` to decide what to summarize
- [[Turn Lifecycle]] — each turn's `before_model`/`after_tool` hooks append events that flow into history
- [[AgentProfile]] / [[build_agent]] — the system prompt installed via `set_system_message`
- [[Task Engine]] — task-engine runs use `transient=True` conversation scopes

## Sources

- None beyond the modules listed in `paths` — no external design doc was consulted for this page.
