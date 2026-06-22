---
title: ConversationHistory
type: entity
tags: [conversation, history, messages, persistence]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - SDK Overview]]", "[[Source - Server Overview]]"]
---

# ConversationHistory

## Overview

`ConversationHistory` (in `sdk/context/_history.py`) is the in-memory representation of a conversation's message list. It provides controlled access to the messages array with helpers for system message management, range deletion, and insertion — operations needed by the compaction strategy. Conversations are cached in-memory (LRU, 25 slots) in the message handler and loaded from disk on cache miss.

## Details

**Constructor:** `ConversationHistory(messages: list[dict] | None, instance_id: str = "")`

**Key properties/methods:**
- `messages` — full message list including system message
- `non_system_messages` — all messages except the system message
- `system_message` — the current system message dict, or None
- `set_system_message(content)` — inserts or replaces the system message at position 0
- `append(message)` — appends a message to the list
- `drop_range(start, end)` — removes messages at `[start:end]`
- `insert(index, message)` — inserts a message at a position
- `get_mutable(index)` — returns the dict at index (for in-place mutation, e.g. intent extraction)
- `instance_id` — the conversation ID string (for logging)

**Persistence:** `PersistenceHook` calls `save_conversation_history(conversation_id, history.non_system_messages)` at turn end — the system message is excluded because it's re-generated each turn

**Loading:** `load_conversation_history(conversation_id)` → `list[dict] | None`; None means new conversation

**LRU cache:** `_conversations: OrderedDict[str, ConversationHistory]` in `message_handler.py`; max 25 entries; eviction skips active turns

## Related Entities

- [[ContextManager]] (reads history for token estimation)
- [[LLMCompactionStrategy]] (mutates history via `drop_range` / `insert`)
- [[PersistenceHook]] (persists history at turn end)
- [[MessageHandler]] (owns the LRU cache)

## Sources

- [[Source - SDK Overview]]
- [[Source - Server Overview]]
