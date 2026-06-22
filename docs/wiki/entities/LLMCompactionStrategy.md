---
title: LLMCompactionStrategy
type: entity
tags: [compaction, context, summarization, strategy]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - SDK Overview]]"]
---

# LLMCompactionStrategy

## Overview

`LLMCompactionStrategy` (in `sdk/context/_strategy.py`) is the primary `ContextStrategy` implementation. When the context window fills past a threshold, it sends older messages to an LLM for summarization, replaces them with a compact summary, and optionally extracts a user intent history. This allows agents to work on long tasks without hitting context limits.

## Details

**Trigger:** `BEFORE_MODEL_CALL` when `stats.fill_ratio >= threshold`

**Constructor:**
```python
LLMCompactionStrategy(threshold=0.75, keep_recent_groups=2, summary_model=None)
```

**Algorithm:**
1. Pin the first user message (it stays in history but may be updated with intent history)
2. Count recent "assistant message groups" to keep verbatim (`keep_recent_groups=2`)
3. Everything else is the "compactable" range
4. Extract prior summary if the compactable range already contains one
5. Serialize compactable messages (with deduplication, truncation, thinking excerpts)
6. If serialized text fits in one chunk: single LLM summarization call
7. If too large: chunk-based summarization then merge
8. Optionally extract user intent history (if multiple user messages)
9. Persist a `SummaryRecord` for evaluation purposes
10. Replace compactable range with `assistant` message containing summary
11. Update pinned user message with intent history (if extracted)
12. Unload the compaction model from Ollama to free VRAM

**Serialization (`_serialize_messages`):**
- Deduplicates browser page snapshots (keeps only last per URL)
- Truncates tool results per-tool: `read_file`/`grep`/`run_bash_cmd` get 1500 chars; unknown tools get 200
- Strips trivial tool results (`{"success": true}`, empty stdout, etc.)
- Includes truncated `thinking` excerpts (200 chars) when assistant content is empty

**Chunking:** splits messages at assistant group boundaries (never splits a tool call from its results)

**Intent extraction:** called when conversation has multiple user messages; extracts how user's request evolved; replaces pinned message with `[User intent history]\n{history}`

**Compaction model:** from `settings.compaction_provider` / `settings.compaction_model` / `settings.compaction_options`; `None` → compaction disabled

**VRAM management:** after compaction, shells out to `ollama stop {model}` (30s timeout)

**Summarization prompt:** structured 3-section format (Completed Work, Key Data, Current State) with explicit rules about preserving facts over process

## Related Entities

- [[ContextManager]] (runs this strategy)
- [[ConversationHistory]] (mutated by this strategy)
- [[ContextStrategy]] concept
- [[Settings]] (provides compaction model config)
- [[SummaryRecord]] (persisted for eval)
- [[OllamaProvider]] (unloaded after compaction)

## Sources

- [[Source - SDK Overview]]
