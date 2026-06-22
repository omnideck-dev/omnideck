---
title: Context Compaction
type: concept
tags: [context, compaction, summarization, llm, tokens]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - SDK Overview]]"]
---

# Context Compaction

## Overview

Context Compaction is the mechanism Omnideck uses to prevent the agent from running out of context window space on long tasks. When the context fill ratio exceeds a configurable threshold, older messages are summarized by an LLM and replaced with a compact summary, while recent messages are kept verbatim.

## How It Works

**Trigger:** `LLMCompactionStrategy` runs at `BEFORE_MODEL_CALL`; fires when `context_used / context_limit >= threshold` (default 0.75)

**What is preserved:**
- System message (always)
- The first user message (pinned) — may be updated with extracted intent history
- The 2 most recent "assistant message groups" (an assistant turn + all its tool results)
- The summary itself (inserted at the compactable range boundary)

**What is summarized:**
- Everything else — the older conversation body

**Summarization process:**
1. Serialize messages for the LLM (truncating tool results, deduplicating browser snapshots, including thinking excerpts)
2. If content fits in one LLM call: single pass
3. If too large: chunk, summarize each chunk, merge chunk summaries
4. Extract user intent history (if multiple user messages exist)
5. Replace compactable range with an `assistant` message prefixed with `[Conversation summary — earlier messages were compacted]\n\n{summary}`
6. Unload the compaction model from Ollama (VRAM recovery)

**Intent extraction:** when the user has sent multiple messages (topic changes), extracts a concise history of how their requests evolved; replaces the pinned first user message with `[User intent history]\n{history}`

**Compaction model:** configured via `settings.compaction_provider/model/options`; independent of the main chat model; can use a smaller/faster model for summarization

**Evaluation:** every compaction persists a `SummaryRecord` (id, created_at, model, input_messages, summary_text, fill_ratio, elapsed_seconds, conversation_id) for quality evaluation

**VRAM management:** after compaction, shells out `ollama stop {model}` to free GPU memory before the main agent's next LLM call

## Key Details

- Token estimation uses `chars / 4` approximation (not a real tokenizer)
- `keep_recent_groups=2` means the 2 most recent assistant turns are always preserved verbatim
- Tool results are truncated per-tool: `read_file`/`grep`/`run_bash_cmd` → 1500 chars; unknown → 200 chars
- Browser page snapshots are deduplicated (only the last per URL)
- Trivial tool results (`{"success": true}`, empty stdout) are entirely omitted from serialization
- Summarization prompt enforces a 3-section structure: Completed Work, Key Data, Current State

## Open Questions

- Does the `keep_recent_groups` count include tool results, or only assistant messages? The code says assistant messages only, with interleaved user/tool messages included automatically.
- What happens if the compaction LLM is the same as the main model? Potential VRAM contention.

## Sources

- [[Source - SDK Overview]]
