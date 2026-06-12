# Events-first branch: work inventory + replay plan

Status snapshot (keep this section current):

- Working branch: `main-shell-redesign`
- Branch HEAD: `c5e0752` — "Merge origin/main into main-shell-redesign"
- `origin/main`: `57a7ad8` — this is the merge-base, i.e. origin/main is fully folded into the branch
- Commits on branch not on origin/main: **20**
- Uncommitted working-tree changes: the **provider-error surfacing + turn_end-ownership** work (16 modified, 1 new file) — see Part A §5
- Total diff vs origin/main (committed + uncommitted): ~124 files, ~9.5k insertions / ~4.6k deletions
- Nothing is pushed. The merge commit and all feature work are local only.

The goal: replay this large body of work onto a fresh worktree branch off `origin/main`, in small reviewable chunks, so it can be reviewed (and eventually shipped) without auditing a 124-file diff at once.

---

## Part A — Inventory of work on the branch

### 1. Events-first persistence (the core refactor)
`events.jsonl` is the conversation source of truth; the LLM/message view is derived, and compaction is a non-destructive event.

- `sdk/events/` — event primitives. Old push-based `EventDispatcher` removed; events now write to the **active conversation** (`set/get/reset_current_conversation`, `publish_event` → `conv.add_event`). New payloads: `UserMessagePayload`/`UserAttachment`, `IterationPayload`/`IterationToolCall`, `ToolResultPayload`, the `Compaction*` family. `AgentEvent` gained a stable `id` + `to_flat_dict()`.
- `conversations/` — `events.jsonl` log writer (`EventsLogWriter`, `_PERSISTED_TYPES` allowlist) + store reading from events.jsonl; `conversation_exists` checks `events.jsonl`.
- `sdk/context/` — `build_llm_history` derives the LLM view from events (strict whitelist: only `user_message`/`iteration`/`tool_result`/`compaction` become messages); `events_for_agent` defines a thread; `ConversationHistory.scoped_events`. Includes the **compaction profile-switch fix** (kept-bounds scoped to the root thread, not `agent_name`).
- `sdk/hooks/`, `sdk/turn/`, `sdk/tools/_spawn_agent.py`, `sdk/skills/_resolve.py`, `sdk/__init__.py` — composition path; `_resolve.py` uses a function-local `conversations` import to break the `conversations ↔ sdk.skills` cycle.
- `server/message_handler.py`, `tasks/_executor.py` — events-first turn orchestration.
- `migrations/_007_events_first.py` — legacy → events.jsonl; derives `depth`/`parent_id` from `agent_id`, normalizes timestamps, sorts by parsed instant. (Migration `006_install_default_skills` is the upstream canonical 006.)
- **Panel state is NOT in the event log.** The UI shows only the latest browser snapshot per tab and the last 50 terminal commands per agent, so both live in bounded overwrite-in-place sidecars per conversation: `browser_tabs.json` (`conversations/_browser_tabs.py`, `BrowserTabsWriter`) and `terminal.json` (`conversations/_terminal.py`, `TerminalWriter` — records running/completed only; streaming chunks are live-display only since completed carries the full output). Real logs were >90% screenshots / up to 45% terminal chunks before the split. Migration 007 routes both into sidecars during first-run conversion from main's format (the real upgrade path); 008/009 convert stores that ran an earlier build of this branch (back up, strip lines, build sidecars; no-op on fresh installs). Resume returns `browser_tabs` + `terminal` from the sidecars; the FE dispatches them after event replay. Main never had the per-frame screenshot problem (its AgentEventBufferHook kept one slot per agent) — persist-everything was this branch's regression, now fixed stronger than main (per-tab, bounded, out of the log).

### 2. Editable skills (#28, already merged earlier)
`build_agent_state(profile, conversation_id=)` composes tools per turn; `LoadedSkillHook` injects skill prompts before_model (not baked into the system message); `skill_ids` (all) vs `loaded_skill_ids` (runtime delta); `persist_loaded_skills` writes only the delta.

### 3. Provider fixes
- `sdk/providers/_ollama.py` — context window via `modelinfo` (was `model_info`).
- `sdk/providers/_fake.py` — balanced nested-`SPAWN` parsing; **`PROVIDERFAIL` directive** (see §5).

### 4. UI (events-first)
- `useStreamingChat.js` — `turns` derived from an events array (`_buildTurns`) + in-flight iteration buffer + optimistic user prompt; dropped the `tool_call` SSE wire.
- Components: `Turn`/`Message`/`ChatPanel`/`ChatMessages`, `AgentNetwork`/`ActivityRail`, `CompactionChip`/`CompactionRow`, `PreviewPanel`. Preview identity keyed by **full path** (`file:${path}`). Mobile app shell removed (folded into responsive desktop).
- Nav-back fix: clicking the active conversation navigates back instead of re-resuming.

### 5. Provider-error surfacing + turn_end ownership (UNCOMMITTED — this session)
This is the newest, still-uncommitted slice. Two tightly-coupled changes:

**(a) Surface turn errors in the UI.** Mid-turn provider errors (e.g. a 429) were swallowed and never reached the UI. Root cause traced through three dead error paths; the real regression was that the events-first UI stopped rendering loose `content` events.
- `sdk/events/_models.py` + `__init__.py` — new typed `ErrorPayload {type:"error", message, retryable}` (+ union + exports).
- `sdk/turn/_execution.py` — `run_turn`'s except publishes `ErrorPayload` with the clean `str(exc)` provider message. **Transient**: `error` is not in `_PERSISTED_TYPES`, so it's shown live but not persisted; `build_llm_history` ignores it (unknown type), so the model never sees it.
- `server/ui/src/hooks/useStreamingChat.js` — `'error'` added to the render event set; `_buildTurns` adds a root `error` child; sub-agent errors route to the activity view.
- `server/ui/src/components/Turn.jsx` + `ActivityRail.jsx` — render the error via the `Callout` (tone="danger") design-language primitive.
- `sdk/providers/_fake.py` + `tests/e2e/_protocol.py` — `provider_fail(message, mid=bool)` directive: fails before-stream or mid-stream.
- Faster retry backoff in `_execution.py`: retries 5→2, delay cap 32s→8s.
- Message spacing bumped (`Message.module.css` 4px→12px) + thinking placeholder for in-flight turns with no output yet.

**(c) Mid-stream stop persists partial output** (ports PR #34's second commit, adapted to events-first).
- `sdk/turn/_execution.py` — `check_stop()` after each streamed delta; on stop, publishes a partial `IterationPayload(stopped=True)` with the streamed-so-far content/thinking (instead of the PR's `history.append`, which doesn't fit our derived-history model), then re-raises. `IterationPayload` gained a `stopped: bool` field.
- `useStreamingChat.js` — graceful stop: `stopGeneration` sets a `stopRequested` flag and leaves the stream open until `turn_end` (so the backend can flush the partial) instead of killing `isStreaming` immediately; `stopRequested` reset on turn end / new conversation; exposed from the hook.
- No visual stopped-marker (matches ChatGPT/Claude.ai — the partial just stays as a normal assistant message). `stopped` is threaded through `_buildTurns` as metadata but nothing renders it.
- `DesktopApp`/`ChatPanel`/`ChatInput` — `stopRequested` threaded to the stop button (shows "Stopping…", disabled).
- Tests: `test_execution.py` stop-mid-stream persists a stopped iteration with the partial; vitest for the stopped child + marker.

**(b) turn_end owned by `turn_scope`** (folds in PR #34's intent, adapted to events-first).
- `sdk/turn/_turn.py` — `turn_scope(conversation=None, conversation_id=None)` now binds the conversation and emits the **single** `turn_end` per user turn in its finally (while the conversation is still bound). Imports `publish_event`/`AgentEvent`/`TurnEndPayload`/`set/reset_current_conversation` from `sdk.events` (verified no import cycle).
- `sdk/turn/_execution.py` — removed `_publish_turn_end()` and its three call sites; kept the `ErrorPayload` publish.
- `server/message_handler.py` + `tasks/_executor.py` — observers now subscribe **around** `turn_scope` (so the final `turn_end` still reaches them); callers no longer do `set/reset_current_conversation` or emit `turn_end`.
- Why: a sub-agent's tool loop ending must not signal the whole user turn is over. This is what makes "sub-agent errors are recoverable, parent continues" behave correctly.
- Tests: `test_message_handler_bridge.py` (one `turn_end`, last, after root completion), `test_execution.py` (error event published; stale comment fixed).

Test status for the whole branch incl. uncommitted: **unit 1455, vitest 351, e2e 180 — all green.**

---

## Part B — Replay plan (chunk onto a fresh worktree)

### Decision already made (do not relitigate)
For the **backend** events-first cutover, "small chunks" and "green-at-every-commit" cannot both hold. Removing the dispatcher + the conversations API change force turn/context/conversations/skills/hooks/tasks/message_handler to move together, or unit collection fails. Expand/contract (keeping the old dispatcher alive transitionally) was rejected as a pretzel. **Chosen approach: small, readable chunks reviewed before commit; green is verified only at the backend boundary, not per chunk.** The UI chunks *can* stay small and vitest-green individually (independent of the Python import graph).

### Mechanics
1. Worktree: `/home/larry/repos/omnideck.worktrees/events-first-review` already exists (currently reset to old baseline — rebuild it).
2. Base = current `origin/main` (`57a7ad8`). FINAL = `main-shell-redesign` HEAD **after committing the §5 work** (commit it first so FINAL is a clean tree).
3. Forward-apply FINAL onto base in logical slices: `git checkout FINAL -- <files>` (and `git rm` for deletions). After the last chunk, the cumulative diff vs FINAL must be empty and no file left uncovered (the `/tmp/build_stack.sh` approach did exactly this).
4. Per-chunk: stage → show the user the diff → they review/approve → commit → next.

### Chunk order (leaf-first by import graph)
1. events primitives (`sdk/events/` + tests)
2. conversations persistence (`conversations/` + tests)
3. derived history + compaction (`sdk/context/` + tests)
4. hooks (`sdk/hooks/` + tests)
5. turn execution + spawn + skills bridge + sdk facade (`sdk/turn/`, `_spawn_agent`, `_resolve`, `sdk/__init__`) — **includes the turn_scope turn_end ownership**
6. providers (ollama modelinfo + fake provider incl. `PROVIDERFAIL`)
7. migration 007
8. message_handler + task executor  ← **backend review boundary; first point the backend imports/runs**
9. UI hooks (replay/agent-state/preview/streaming)
10. UI chat rendering + app shell
11. compaction chip + activity-rail compaction row
12. agent network + activity rail (incl. error row)
13. preview panel
14. remove mobile shell  ← **UI complete; rebuild UI and the app runs end-to-end**
15. e2e protocol + page objects (incl. `provider_fail`)
16. e2e chat + conversations suites (incl. `test_provider_errors.py`)
17. e2e network/shell/settings suites  ← **stack tip; full suites pass here**
18. remove compaction-eval dev harness
19. docs/plans

Honest commit-message rule: only the **tip** is verified green. Intermediate commits are leaf-first slices of the final tree on top of main and are **not** expected to import/run standalone — say "review boundary," do not claim "imports/boots/passes here" unless actually checked out and run.

### Provider-error + turn_end placement
The §5 work is not a separate chunk — it lands inside its natural homes: the `ErrorPayload` model in chunk 1, the `run_turn`/`turn_scope` changes in chunk 5, the fake-provider `PROVIDERFAIL` in chunk 6, the UI rendering in chunks 10/12, the e2e in chunks 15–16.

---

## Part C — Constraints / standing rules

- Commit only when explicitly asked; confirm before every push (per-push).
- Never run e2e unprompted — it's single-tenant (`computron_e2e`, fixed port); cross-branch concurrent runs cause phantom failures.
- Never commit real conversation data or PII; runtime data lives at `~/.computron_9000/`, not the repo.
- Use docker (not podman); dev container `computron_virtual_computer`.
- Never patch around test failures.

## Part D — Open items / outstanding

- [ ] Commit the §5 provider-error + turn_end work on `main-shell-redesign` (one commit, or split: turn_end refactor / error+backoff+spacing).
- [ ] PRs #34/#35/#36 are open upstream on the **old dispatcher** architecture; all three are already ported to our branch in events-first form:
  - #34 turn_end ownership → `turn_scope`; partial-on-stop → stopped `IterationPayload`.
  - #35 (fake "user requested stop, wrap up" message removed) → `StopHook.after_model` no longer publishes the synthetic `user_message` event (on our branch it also rendered as a fake user bubble and persisted to events.jsonl).
  - #36 (skip thinking-only stop history) → guard in `build_llm_history`: an iteration event with no content and no tool_calls never derives into an assistant message (the event stays in the log for the UI). Upstream fixed this at persist time; ours is at derivation time — the sanitize boundary their plans doc describes as the desired design.
  - When these merge to origin/main and we re-merge: `_turn.py`/`_execution.py`/`_stop_hook.py`/`useStreamingChat.js`/`ChatInput`/`ChatPanel` + test files conflict — resolve **in our favor**. #34 touches `MobileApp.jsx`, which we deleted — drop that hunk. plans/future_refactor_ideas.md additions merge cleanly (ours is identical to origin/main).
- [ ] Old conversation histories were restored into the live store (82 convs got `history.json` back) so the `main` branch can read them alongside events.jsonl. Additive/reversible — delete the added `history.json`/`events.json`/`sub_agents` to undo.
- [ ] Rebuild the review worktree (it was reset to baseline; the earlier 19-commit stack is gone) and run the chunked replay above.
