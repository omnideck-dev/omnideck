---
title: Context Compaction
type: concept
tags: [sdk, context, compaction, memory, llm]
created: 2026-07-07
updated: 2026-07-07
verified_commit: 6a5625d
paths:
  - "sdk/context/"
---

# Context Compaction

## Overview

Context compaction is the process of reducing conversation history when it approaches the model's context window limit, so the agent can continue working without hitting a hard token cap. The SDK implements this via a pluggable `ContextManager` that tracks token usage and fires registered strategies when a configurable threshold is crossed.

## How It Works

### ContextManager

`sdk/context/_manager.py:ContextManager` is constructed per-turn. It holds:
- A reference to the `ConversationHistory`
- The context window size (in tokens) and compaction threshold (fill ratio, default 0.75)
- A list of `CompactionStrategy` objects to try in order
- A `TokenEstimator` for counting tokens without calling the model

The `ContextHook` (one of the default hooks) calls `ctx_manager.maybe_compact(history, iteration)` in its `before_model` phase. If the estimated fill ratio exceeds the threshold, it fires the first strategy that can run.

### Token Estimation

`sdk/context/_estimator.py` estimates token counts using tiktoken's `cl100k_base` encoding (a reasonable approximation across most contemporary LLMs). It counts the current history and divides by the context window to get the fill ratio.

### LLMCompactionStrategy

`sdk/context/_strategy.py:LLMCompactionStrategy` is the default strategy. It:
1. Identifies **message groups** — each assistant message plus its associated tool-call results — so tool results are never orphaned from the call that created them.
2. Keeps the most recent N groups verbatim (a fixed count to preserve recent context).
3. Summarizes older groups by calling the LLM with a summarization prompt.
4. Replaces the old groups in history with a single summary message.

### Message Groups

A message group is defined as one assistant message plus all immediately-following tool result messages. Compaction counts backward from the tail of history, preserving the K most recent groups. Groups earlier than K are summarized or dropped.

This invariant — tool results never split from their tool calls — prevents a class of LLM confusion where the model sees a tool result with no prior call to explain it.

## Where It Lives

| File | Role |
|------|------|
| `sdk/context/_manager.py` | `ContextManager` |
| `sdk/context/_strategy.py` | `LLMCompactionStrategy`, `_count_kept_by_assistant_groups` |
| `sdk/context/_estimator.py` | Token counting |
| `sdk/context/_history.py` | `ConversationHistory` (the data structure) |
| `sdk/hooks/_context_hook.py` | `ContextHook` — calls `maybe_compact()` before each model call |

## Key Details

- **Per-profile threshold:** `compaction_threshold` is set on the `AgentProfile` and passed to `ContextManager`, so different profiles can have different aggressiveness (e.g., a research agent that wants a large window vs. a quick-task agent with a tight budget).
- **Context usage events:** after each model call, a `ContextUsagePayload` event is emitted with `context_used`, `context_limit`, `fill_ratio`, and `compaction_threshold`. The UI's `ContextMeter` component renders these as a fill bar.
- **`ToolResultCapHook`** is a complementary mechanism: it truncates individual tool results that are individually oversized, preventing a single large result from filling the window before compaction can fire.

## Open Questions

- The compaction summarization call counts against the same model and conversation, meaning the summary is injected mid-turn; if the summary itself is long it could trigger another compaction cycle.

## Sources

- `docs/sdk_semantics.md` — Message Group definition
