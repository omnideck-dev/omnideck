---
title: Context Compaction
type: concept
tags: [agent-core, agent-runtime, context, compaction, summarization]
created: 2026-07-07
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "agent_core/context/"
  - "agent_core/hooks/_context_hook.py"
  - "agent_runtime/_compaction.py"
---

# Context Compaction

## Overview

Compaction summarizes older turns of a conversation with an LLM call when the context
window fills up, so the agent can keep working without hitting the model's token limit.
It fires automatically — before a model call, if the fill ratio crosses a threshold —
and is implemented entirely as a `ContextStrategy` plugged into the generic
`ContextManager`/`ContextHook` machinery (see [[Hooks System]]).

## How It Works

### Trigger

`ContextManager.before_model()` (`agent_core/context/_manager.py`) runs every strategy
whose `trigger == TriggerPoint.BEFORE_MODEL_CALL` and whose `should_apply()` returns
true. `LLMCompactionStrategy.should_apply()` (`agent_runtime/_compaction.py`) checks
`stats.fill_ratio >= threshold` — the per-profile `compaction_threshold` (default 0.75).
`stats` comes from `ContextManager.stats`, which estimates tokens over the live message
list and currently-loaded tools via `estimate_tokens()` (`_estimator.py`).

### What gets kept vs. summarized

`LLMCompactionStrategy.apply()`:
1. Finds and pins the first user message (so the original ask isn't lost) unless it's
   already a prior summary.
2. Walks backward counting **assistant message groups** (`_count_kept_by_assistant_groups`)
   to find how many of the most recent `keep_recent_groups` (default 2) groups to
   preserve verbatim — a group is one assistant message plus whatever tool
   results/user messages sit between it and the next kept boundary. This guarantees a
   tool call and its result are never split across the summarized/kept boundary.
3. Everything else in between becomes `compactable`.

### Summarization

- Resolves the summarizer provider/model/options from settings
  (`compaction_provider`/`compaction_model`/`compaction_options`) — if unset, compaction
  is silently disabled (`should_apply` would still return true, but `apply()` returns
  early via `_resolve_model()` returning `None`... actually: `apply()` asserts a resolved
  model exists before calling the summarizer, so an unconfigured compaction model surfaces
  as a user-facing `ProviderError` the next time it would fire, not a silent skip).
- `_serialize_messages()` renders the compactable messages into a compact text form,
  applying per-tool-type truncation caps (`_TOOL_RESULT_CAPS` — e.g. 1500 chars for
  `read_file`/`grep`/`run_bash_cmd`, 200 for `click`/`fill_field`) and deduplicating
  repeated browser page snapshots for the same URL (`_dedup_page_snapshots`).
- If the serialized text exceeds a size derived from the summarizer's own context
  window (`_CTX_INPUT_FRACTION = 0.6`), it's chunked (`_split_into_chunks`, never
  splitting a tool-call/result pair) and summarized chunk-by-chunk, then the chunk
  summaries are merged in a final pass.
- The summarizer is prompted with a fixed structure: `## Completed Work`, `## Key
  Data`, `## Current State` — biased toward preserving facts/data over narration of
  steps taken.
- If the conversation had more than one distinct user message in the compactable
  range, a second LLM call (`_extract_intent`) consolidates them into an intent history,
  so a user who changed their ask mid-conversation doesn't leave a stale first message
  pinned forever.

### Publishing the result

The strategy never mutates history directly — it publishes a `CompactionPayload` event
(`kept_from_id`, `kept_to_id`, `summary_text`, optional `user_intent_summary`, and a
`CompactionStats` block for the UI's summary chip). `build_llm_view()`
(`agent_core/context/_view.py`) is what actually reconstructs history around the latest
compaction event on the next read — see [[Event System]].

### Publishing context usage

Independent of compaction firing, `ContextManager.after_model()` publishes a
`ContextUsagePayload` after every LLM call (`context_used`, `context_limit`,
`fill_ratio`, the active `compaction_threshold`) so the UI can render a live context
meter regardless of whether compaction has ever triggered.

## Where It Lives

| File | Role |
|------|------|
| `agent_core/context/_manager.py` | `ContextManager` — orchestrates strategies, publishes usage events |
| `agent_core/context/_strategy.py` | `ContextStrategy` protocol, `TriggerPoint` enum |
| `agent_core/context/_estimator.py` | `estimate_tokens()` |
| `agent_core/context/_view.py` | `build_llm_view()` — reconstructs history around the latest compaction |
| `agent_core/hooks/_context_hook.py` | `ContextHook` — wires the manager into the turn loop |
| `agent_runtime/_compaction.py` | `LLMCompactionStrategy` — the only strategy currently implemented |

## Key Details

- **Message Group:** an assistant message plus its immediately-following tool results.
  Compaction never splits a group — this prevents orphaned tool results in the
  model-facing history.
- **Compaction is additive to the event log, not destructive.** Older events remain on
  disk for audit; only the *derived LLM view* changes, by pointing at the latest
  compaction event.
- **Model unloading:** after a successful (or failed) summarization call,
  `_unload_model()` shells out to `ollama stop <model>` to free VRAM — relevant mainly
  for local models where the summarizer and chat model might not both fit in memory at
  once.
- **No model/provider configured → hard failure, not silent skip.** A `ProviderError`
  with a user-facing message surfaces through the normal turn error path, telling the
  user to configure a compaction model in Settings.

## Open Questions

- Whether `estimate_tokens()` is a true tokenizer-based count or a character-based
  approximation — worth confirming against `_estimator.py` in a future pass if the
  distinction matters for a specific investigation.

## Sources

- None beyond source code for this pass.
