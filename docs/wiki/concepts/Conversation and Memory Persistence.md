---
title: Conversation and Memory Persistence
type: concept
tags: [conversation, memory, persistence, json, disk]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - Server Overview]]", "[[Source - Tools Overview]]"]
---

# Conversation and Memory Persistence

## Overview

Omnideck persists conversation history, agent events, memory, loaded skills, and profile associations to disk. The `conversations/` package manages all conversation-related storage; `tools/memory/memory.py` manages the key-value memory store. Both use atomic writes for crash safety.

## How It Works

**Conversation storage (`conversations/_store.py`):**
- Base path: `{home_dir}/{conversation_id}/`
- `history.json` — `list[dict]` of non-system messages (system message excluded; rebuilt each turn)
- `events.json` — `list[AgentEvent]` of lifecycle/preview events (file outputs, browser screenshots, etc.)
- `loaded_skills.json` — list of skill IDs loaded at runtime (the cross-turn delta)
- `metadata.json` — conversation title, pinned flag, profile ID association
- `preview_state.json` — UI preview panel state (open files, active tab, visibility flags)
- `sub_agents/{name}/{id}/history.json` — sub-agent histories (separate from main)
- `summaries/{id}.json` — `SummaryRecord` objects from compaction (for eval)

**Conversations listing:** `list_conversations()` scans directories; returns `ConversationSummary` objects with metadata

**Conversation cache:** `OrderedDict` in `message_handler.py` (max 25 entries, LRU); disk is authoritative; cache is evicted but not invalidated

**Memory persistence (`tools/memory/memory.py`):**
- Single `{home_dir}/memory.json` file
- Format: `{key: {value: "...", hidden: false}}`
- Atomic write: tempfile in same directory + `Path.replace()`
- Loaded on every system message refresh (before each LLM call)

**Event persistence:**
- `AgentEventBufferHook` collects lifecycle events during the turn (subscribed to `EventDispatcher`)
- At turn end (outside `agent_span`): `save_agent_events(conv_id, buffered_events)` writes to `events.json`
- Only certain payload types are buffered (file outputs, browser screenshots, tool_created, etc.); streaming content events are NOT persisted

**Profile association:**
- `save_conversation_profile(conversation_id, profile_id)` saves which agent was used
- `load_conversation_profile(conversation_id)` restores on resume — so the UI shows the right agent name

## Key Details

- System message is NOT persisted (memory-injected, profile-derived, regenerated each turn)
- Loaded skills delta IS persisted; profile baseline skills are NOT (re-derived each turn)
- `conversation_exists(id)` lets the UI distinguish "new" from "never seen"
- `save_conversation_pinned(id, pinned)` for user bookmarking
- Title generated asynchronously after the first turn (background task)

## Open Questions

- Is `events.json` append-only or rewritten on each turn? (TODO: check `save_agent_events` implementation)
- What is the exact schema of `preview_state.json`?

## Sources

- [[Source - Server Overview]]
- [[Source - Tools Overview]]
