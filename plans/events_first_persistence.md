# Events-First Persistence

Status: design validated by a practice migration on real conversations (91/91 lossless rebuild). Not yet implemented in the SDK.

## Problem

Today the conversation has two on-disk representations:

- `history.json` — LLM-format messages, mutated destructively by compaction
- `events.json` — partial UI event log (lifecycle + screenshots + terminal + file_output only)
- plus `summaries/*.json` (compaction audit) and `sub_agents/*.json` (per-sub-agent LLM history)

These stores drift, duplicate data, and force the frontend to do a fragile merge (`_historyToMessages` + `_mergeFileOutputs` + synthetic-agent dance) when reconstructing the UI on resume. Compaction is destructive on `history.json` so the UI's view of the past shrinks when the model's context shrinks.

## Goal

One source of truth (`events.jsonl`), with `history.json` (LLM context) derived on demand. Compaction becomes non-destructive: the UI shows the full conversation forever; only the LLM's view shrinks.

Specifically:

- UI sees the original conversation — every user message, every assistant response, every tool result — regardless of how many compactions have happened.
- LLM sees the compacted view (summary substitutions, intent-history pin overrides).
- One code path for resume + live (frontend dispatches events from the same handler in both cases).
- No `history.json`, no `sub_agents/*.json`, no `summaries/*.json` after migration. Just `events.jsonl` + `metadata.json` + `scratchpad.json` per conversation.

## Data model

Storage: `{conv_dir}/events.jsonl` — newline-delimited JSON, one event per line, append-only.

Common envelope on every event:

```json
{
  "id": "evt_<uuid>",
  "type": "<discriminator>",
  "timestamp": "ISO-8601",
  "conversation_id": "<conv uuid>",
  "agent_id": "<span context id>"
}
```

`id` is the per-event UUID — used by `CompactionPayload`'s `kept_from_id` / `kept_to_id` references. `conversation_id` is essential for filtering: a single conversation has many `agent_id`s (each turn spawns a fresh root span; sub-agents have their own ids). `agent_id` is the span the event was emitted under.

### Event types

Vocabulary (per `docs/sdk_semantics.md`):

- **conversation** — persistent multi-turn exchange identified by `conversation_id`.
- **turn** — one user message → agent response cycle; bracketed by `agent_started` / `agent_completed` at the root level.
- **iteration** — one LLM call within a turn (produces thinking + content + tool_calls together as a single completion). A turn contains many iterations.

| type | payload (beyond envelope) | notes |
|---|---|---|
| `user_message` (new) | `content: str`, `attachments: [{filename, content_type, path}]` | original text + attachment list kept separate; UI shows original, `build_llm_history` augments for LLM |
| `agent_started` | `agent_name`, `parent_agent_id`, `correlation_id`, `instruction`, `profile_name` | as today |
| `agent_completed` | `agent_name`, `status` | as today |
| `iteration` (new — replaces split ContentPayload + ToolCallPayload + thinking) | `iteration_index: int`, `thinking: str \| null`, `content: str \| null`, `tool_calls: [{id, name, arguments}]` | one event per LLM call — bundles everything the model produced in that completion. Matches history.json's assistant-message shape so migration + rebuild are trivial. |
| `tool_result` (new) | `tool_call_id: str`, `tool_name: str`, `content: str` | matched to a tool_call inside an iteration via `tool_call_id` |
| `spawn_requested` | `correlation_id` | as today |
| `file_output` | `tool_call_id` (new), `filename`, `content_type`, `path` | tool_call_id lets us slot file events after their triggering tool_call (currently approximated at end of turn) |
| `browser_screenshot` | `url`, `title`, `screenshot` (base64) | dedupe latest-per-agent at save time |
| `terminal_output` | `cmd_id`, `cmd`, `status`, `stdout`, `stderr`, `exit_code` | as today, kept bounded per agent |
| `context_usage` | `context_used`, `context_limit`, `fill_ratio`, `compaction_threshold`, `iteration_index`, `max_iterations` | dedupe latest-per-agent at save time |
| `turn_end` | (none) | UI signal, marks turn boundary |
| `compaction` (new) | see below | non-destructive — covers an event range, never deletes |

CompactionPayload in detail:

```json
{
  "id": "evt_<uuid>",
  "type": "compaction",
  "timestamp": "...",
  "conversation_id": "...",
  "agent_id": "<owning agent id>",
  "kept_from_id": "evt_<first event of the recent-kept group>",
  "kept_to_id":   "evt_<last event in the log when this compaction fired>",
  "summary_text": "...",
  "user_intent_summary": "..." | null,
  "audit": {
    "model": "kimi-k2.5:cloud",
    "input_char_count": 12345,
    "elapsed_seconds": 4.2
  }
}
```

Field semantics:

- **`kept_from_id`** (inclusive) — the first event of the recent-kept group at the moment compaction fired. `build_llm_history` walks events from this id forward (skipping any older compaction events along the way) to assemble the literal portion of the LLM view.
- **`kept_to_id`** (inclusive) — the last event in the log at the moment compaction fired (i.e., the event immediately before this compaction event itself). Currently unused by `build_llm_history` — included for audit, future UI affordances (e.g. "this compaction kept events X..Y"), and per-compaction stats. Negligible cost; loads bears later.
- **`summary_text`** — what the LLM sees in place of the compactable middle (everything between the pin and `kept_from_id`).
- **`user_intent_summary`** — text the LLM sees for the pinned user message at build time. The original `user_message` event in the log is never mutated; the override applies at LLM-view build time only. Compaction still produces it the same way it does today (via the user-request consolidation LLM call); only the name changes — no behavior change.

Only the latest compaction event (max timestamp for this agent) is consulted at LLM-build time. Older compaction events stay in the log as audit-only artifacts — they're skipped during the events traversal.

Fields intentionally NOT stored (derivable or implicit):
- **`covers_start_id`** — implicit. The covered range is always from immediately after the pin to immediately before `kept_from_id`.
- **The previous compaction's summary** — already in the prior compaction event's `summary_text` (filter by agent_id, sort by timestamp, take the prior).
- **`pinned_user_event_id`** — always the first `user_message` event for this `agent_id`; compute at build time.
- **`pinned_pre_compaction`** — derivable from prior state (either the previous compaction's `user_intent_summary` or the original `user_message.content` if no prior compaction).

The `audit` sub-object holds non-load-bearing observability data for compaction-quality evaluation (`docs/summarizer_optimization/`). `build_llm_history` never reads from `audit`.

Skipped from v1 persistence (UI-only signals, ephemeral, not needed for restore): `desktop_active`, `generation_preview`, `audio_playback`, `tool_created`.

Save-time dedupe rule: for `browser_screenshot` and `context_usage`, the appender scans for prior entries of the same `(type, agent_id)` and replaces in place rather than appending. Everything else is pure append.

## build_llm_history

A pure function `build_llm_history(events, conversation_id, root_only=True) -> list[dict]` that walks events and produces an LLM-format message list. Lives in `sdk/context/_history_builder.py` (new).

Algorithm:

1. Filter events to the given `conversation_id`. If `root_only`, restrict to events whose `agent_id` corresponds to a depth-0 span (any `agent_id` that has an `agent_started` event with `parent_agent_id is None` in this conversation). `CompactionPayload` events always included.
2. Resolve compactions: for each compaction, mark every covered event id as "replaced by this compaction." When multiple compactions cover the same event id, the LATEST (by timestamp) wins. Build `covered_by: event_id → compaction` and `pinned_overrides: event_id → override_text`.
3. Find the latest compaction event for this agent (max timestamp; or None if no compactions yet).
4. Emit the pin: locate the first `user_message` event for this agent. Apply `user_intent_summary` from the latest compaction if present (prepend the LLM-side prefix string — `[User intent history]\n` for v1, matching today's wording verbatim; changing this needs summarizer evals first). Emit as `{role: "user", content}`.
5. If a latest compaction exists, emit the summary marker once: `{role: "assistant", content: SUMMARY_PREFIX + summary_text}`.
6. Walk events forward from the kept boundary:
   - No compaction: walk from immediately after the pin.
   - With compaction: walk from `kept_from_id` (inclusive).
   For each event, translate to LLM message:
     - `user_message` → `{role: "user", content}` (with attachment augmentation if attachments present)
     - `iteration` → one `{role: "assistant", thinking?, content?, tool_calls?}` message with the iteration's bundled fields, dropping fields that are null/empty
     - `tool_result` → `{role: "tool", tool_call_id, content}`
     - `compaction` → skip (older compactions are audit-only; latest already emitted in step 5)
     - `agent_started` / `agent_completed` → no message emitted (control events, not LLM content)
     - Other types (browser/terminal/file_output/spawn_requested/context_usage/turn_end) → no message emitted
7. Return the message list.

For sub-agent LLM history: same function with `root_only=False` and an `agent_id` filter argument; returns just that sub-agent's LLM context.

## ConversationHistory becomes a view

`sdk/context/_history.py`'s `ConversationHistory` class keeps its public surface (`non_system_messages`, `set_system_message`, etc.) so the SDK doesn't change. Internally it's a cache over `build_llm_history(events, conv_id)`. Cache invalidates on event append. Each turn: append events, invalidate cache; before next LLM call: cache miss triggers rebuild from events.

For very long conversations the rebuild is linear in event count, with content text bounded by compaction. Realistically sub-100ms even for huge logs. If it ever shows up in profiles, we can cache more aggressively.

Exposes a `message_index_to_event_id: dict[int, str]` mapping (or equivalent) so the compaction strategy can map "LLM message index N is the first kept-recent message" → "event id evt_X" and capture `kept_from_id` correctly at emit time.

## Compaction strategy refactor

`sdk/context/_strategy.py`'s `LLMCompactionStrategy.apply()` becomes:

1. Get current LLM message list from `history.get_messages()` (which calls `build_llm_history`).
2. Compute the pin + compactable + kept split exactly as today.
3. Summarize the compactable range as today.
4. Extract intent if multi-user-message, as today.
5. Map the FIRST event of the recent-kept group → its event id. That's `kept_from_id`. Map the LAST event in the log when this compaction is firing → its event id. That's `kept_to_id`.
6. Emit a `CompactionPayload` event with `kept_from_id`, `kept_to_id`, `summary_text`, `user_intent_summary`, and `audit`.
7. Invalidate the history cache.

No cumulative-range bookkeeping needed. Each compaction records its own boundary at the moment it fires; only the latest compaction is consulted at LLM-build time. Older compactions stay in the log as audit-only artifacts.

No more `history.drop_range`, `history.insert`, `save_summary_record`. The destructive mutation of the pinned message disappears.

### Where iteration events come from

The `iteration` event fires at the natural hook point: `after_model(response, history, iteration_index, agent_name)` in the SDK turn loop. `response` carries the LLM's assembled output for that call — final thinking, final content, final tool_calls. The event-log hook subscribes to this and emits one `iteration` payload with all three fields, plus the `iteration_index` so chronological ordering within a turn is preserved without needing per-event timestamps to be exact.

Live UI streaming (token-by-token rendering) is unaffected: the SSE/wire stream still emits incremental chunks. Those are ephemeral — only the final assembled iteration is persisted.

## Sub-agents

Sub-agents emit events into the same `events.jsonl`, keyed by their own `agent_id`. `build_llm_history(events, conv_id, agent_id=sub_id, root_only=False)` filters to that sub-agent's events when constructing its LLM context. `sub_agents/*.json` files go away.

## Attachment UX (parallel concern)

Today `_augment_message_with_attachments` mutates the user's message content with a `[Attached files written to virtual computer]\n  - file...` footer. The UI displays this verbatim — user sees their own message + the augmentation block as a wall of structured text below their typed prompt.

In events-first:
- `UserMessagePayload` carries `content` (original typed text) and `attachments: list[...]` separately.
- `build_llm_history` calls `_format_attachments(content, attachments)` when building the LLM view (same augmentation logic, deferred to build time).
- Frontend renders attachments as chips beneath the bubble, never as inline text. (`AttachmentChip` already exists.)

The misleading-deleted-file caveat (user attached a file at turn 1, agent deletes it at turn 5, chip still says "you attached this") is acceptable. The chip represents "you attached this at this moment in time," not "this file currently exists." Could later add a visual treatment for files that subsequent events show as deleted, but that's a follow-up.

## Migration

Walks each `{conv_dir}` and produces `events.jsonl` from `history.json` + `events.json` + `summaries/*.json` + `sub_agents/*.json`. Archives the old files under `{conv_dir}/_pre_006/` so rollback is possible.

Validated empirically on 91 real conversations: **100% lossless rebuild** (rebuild via `build_llm_history` produces byte-identical LLM message list to the original `history.json`).

Phases:

1. **Pre-compaction reconstruction:** start with current `history.json`, expand each summary marker (assistant message with `[Conversation summary —` prefix) by replacing it with the corresponding summary record's `input_messages`. Iterate until no markers remain (handles chained summaries). Track which messages came from which summary record (`msg_to_record_id`). If any expansion happened, restore the pinned user message to the absolute original from the earliest record's `user_message_pre_compaction`.

2. **Synthesize per-message events:** walk reconstructed messages, anchored to `events.json`'s root `agent_started` timestamps (one per turn). Each assistant message in history.json becomes one `iteration` event (with bundled thinking + content + tool_calls); each `tool` message becomes one `tool_result` event; each `user` message becomes one `user_message` event. Each turn's events use that turn's anchor's `agent_id` (each turn = fresh root span in the SDK, so per-turn agent_ids are correct). Synthesized timestamps = anchor + sequence offset (1µs per event). For messages with no matching anchor, inherit the previous anchor's identity and advance time by 1s.

3. **Compaction events with per-record boundaries:** for each summary record in `created_at` order, emit a `CompactionPayload`. Each record's `kept_from_id` = the event id of the first event AFTER the messages this record compacted (i.e., the first event of the recent-kept group at the time this record fired). `kept_to_id` = the last event id in the log at the time this record fired. Only the latest compaction will be consulted by `build_llm_history`; older ones are audit-only.

4. **Structural events carried over:** `file_output`, `browser_screenshot`, `terminal_output` from `events.json` get UUIDs and conversation_id added. Their existing timestamps + agent_ids pass through.

5. **Sub-agents:** for each `sub_agents/*.json` file, find the matching agent_started in `events.json` by name + suffix matching. Synthesize events as in phase 2. Sub-agents with multiple user messages but only one anchor inherit the anchor's `parent_agent_id` in the fallback (so they stay tagged as sub-agents, not misclassified as roots).

6. **Combine + write:** sort all events by timestamp, write `events.jsonl` atomically (tmp + rename). Move `history.json`, `events.json`, `summaries/`, `sub_agents/` into `_pre_006/` for rollback. Mark migration done.

Migration is idempotent: if `events.jsonl` already exists, skip.

## Bugs caught during the practice run

(captured here so we don't re-introduce them in the production version)

1. **Per-turn agent_id mismatch.** Each turn in the SDK creates a fresh root span with a unique `agent_id`. Initial implementation forced all events under the first turn's `agent_id`. Fixed: each turn's events use that turn's anchor's `agent_id`.

2. **Multiple summary markers in LLM view (early design iteration).** An earlier version of the design had each compaction event cover its own range with cumulative semantics. After landing on "only the latest compaction matters, older ones are audit-only," the design simplified: each compaction records its own boundary (`kept_from_id` + `kept_to_id`), `build_llm_history` consults only the latest, older ones are skipped during traversal.

3. **Sub-agent fallback misclassified.** When a sub-agent has multiple user messages but only one `agent_started` event in `events.json`, the fallback path was synthesizing `parent_agent_id=None`, classifying those events as root spans. Fix: inherit parent_agent_id from the last real anchor in the fallback.

4. **Orphan summary records.** Some conversations have summary records on disk but no matching summary marker in current `history.json` (the conversation was extended/restarted past compaction without the markers being re-created). Restoring the pin to the earliest record's `user_message_pre_compaction` in this case overrides the current first user message. Fix: only restore the pin if at least one summary marker actually matched a record.

## Implementation order

By scope, files touched, and where risk concentrates.

1. **Schema + new payload types in `sdk/events/_models.py`.**
   Files: `sdk/events/_models.py`.
   Add `UserMessagePayload`, `IterationPayload` (bundles thinking + content + tool_calls — replaces today's `ContentPayload` + `ToolCallPayload` in the persistence stream; live SSE streaming still uses incremental token events that are ephemeral), `ToolResultPayload`, `CompactionPayload`. Extend `FileOutputPayload` with `tool_call_id`.
   ~70 LOC. Zero behavior change yet — payload types exist, nothing emits them.

2. **Emit the new event types from the SDK.**
   Files: `server/message_handler.py` (user_message emit at chat ingress), `after_model` hook (iteration emit — one event per LLM call with thinking + content + tool_calls bundled), `after_tool` hook (tool_result emit, tool_call_id on file_output).
   ~120 LOC. Risk: making sure `after_tool` has access to the tool_call_id for `file_output` payloads emitted from inside the tool's body.

3. **events.jsonl format + writer.**
   Files: new `sdk/hooks/_event_log.py` (replaces `sdk/hooks/_agent_event_buffer.py`), `conversations/_store.py`.
   Full-event capturer subscribes to every payload type, assigns `event.id`, writes one line per event. Save-time dedupe for `browser_screenshot` and `context_usage`.
   ~120 LOC. Risk: making the writer cheap enough that high-frequency events don't bottleneck.

4. **`build_llm_history` + `ConversationHistory` as a view.**
   Files: new `sdk/context/_history_builder.py`, edit `sdk/context/_history.py`.
   The keystone. Pure function, walks events, honors compactions, produces LLM message list. Each `iteration` event maps 1:1 to an assistant message (no grouping needed). `ConversationHistory` keeps its public surface but caches the build result.
   ~200 LOC. Risk: chained compactions have edge cases. Heavy unit testing (the prototype in `/tmp/migrate_006/verify.py` already covers the contract).

5. **Compaction strategy refactor.**
   Files: `sdk/context/_strategy.py`, `conversations/_store.py` (drop `save_summary_record` codepath or keep behind a flag temporarily).
   `LLMCompactionStrategy.apply` emits `CompactionPayload` instead of mutating history. Drop SummaryRecord persistence.
   ~80 LOC.

6. **Attachment fix.**
   Files: `server/message_handler.py`, `sdk/events/_models.py` (UserMessagePayload), `sdk/context/_history_builder.py` (augment for LLM view), `server/ui/src/components/ChatMessages.jsx` (render chips, not inline text).
   ~50 LOC.

7. **Migration script + unit tests.**
   Files: new `migrations/_006_events_first.py`, new `tests/unit/migrations/test_006_events_first.py`.
   Promote `/tmp/migrate_006/migration.py` after cleanup. Promote `/tmp/migrate_006/test_migration.py` (16 tests) as the unit test baseline.
   ~400 LOC including tests.
   Risk: phase-2 mapping from `record.input_messages` to event id ranges, attachment parsing, sub-agent fallback. Heavy fixture testing. The end-to-end validation across all conversations on disk is the real safety net.

8. **Frontend resume simplification.**
   Files: `server/ui/src/hooks/useStreamingChat.js`, `server/ui/src/DesktopApp.jsx`.
   Delete `_historyToMessages`, `_mergeFileOutputs`, the synthetic-agent dance in `onConversationLoaded`. Resume becomes:
   ```js
   for (const ev of data.events) _handleStreamEvent({ payload: ev, agent_id: ev.agent_id }, callbacks);
   ```
   ~80 LOC removed.

9. **PersistenceHook + sub-agent loader removal.**
   Files: `sdk/hooks/_persistence.py` (delete), `server/message_handler.py` (drop PersistenceHook reference), `conversations/_store.py` (drop `save_conversation_history`, `save_sub_agent_history`).
   ~80 LOC removed.

## Open questions / decisions captured

(state after the design + validation pass; nothing blocking implementation start)

### Settled

- **events.jsonl extension.** Going with `.jsonl` since we're breaking the format anyway.
- **LLM-side prefix on `user_intent_summary`.** Keep `[User intent history]\n` verbatim for v1, matching today's wording. Changing this needs summarizer evals first.
- **SummaryRecord persistence during transition.** Fully delete the `summaries/*.json` writer from day one. Migration validated empirically (93/93 byte-perfect rebuild).
- **Old conversations' synthesized timestamps.** Migration anchors synthesized events to `agent_started` timestamps + microsecond offsets within a turn. Pre-migration conversations' "5s ago" displays will be approximate; new conversations will be exact. Acceptable.
- **Concurrency.** events.jsonl is single-writer per conversation. Not relevant for v1 (single server process).
- **Rollback.** No formal rollback. Migration archives old files under `_pre_006/`; we deal with bugs if and when they happen by manually restoring. No feature flag, no parallel writer. Migration validated empirically; if it ships and breaks, manual recovery is acceptable for an unmerged-product persistence change.

### Open before implementation

(none — all decisions captured under Settled)

Note on multi-user histories within a single agent: the nudge feature injects user-shaped messages into a running agent's loop (works for both root and sub-agents). So any agent's history can contain multiple user messages — the initial input plus zero or more nudges. In events-first this falls out naturally: a nudge is a `user_message` event tagged with the receiving agent's `agent_id`. Migration handles this via the same per-user-message turn-opening logic, regardless of root or sub-agent.

### Future / deferred

- **UI mockups for surfacing compaction.** Captured in `project_events_first_persistence.md` memory — needs design before implementing.
- **Compaction algorithm changes** (e.g., dropping intent extraction, restructuring summary prompt). Needs summarizer evals first; not part of this refactor.
- **Multi-process events.jsonl writers** (if we ever support sub-agents in separate processes). Locking or per-process streams that get merged. Not v1.

## What's in `/tmp/migrate_006/`

Practice run artifacts. Not committed.

- `migration.py` — the migration script, ready to promote to `migrations/_006_events_first.py`.
- `test_migration.py` — 16 unit tests with synthetic fixtures. All passing.
- `verify.py` — prototype of `build_llm_history` + a diffing helper. The `build_llm_history` body is essentially production-ready as far as the contract goes.
- `scratch/`, `scratch_full/` — copies of real conversations with migration applied. Used for empirical validation.
