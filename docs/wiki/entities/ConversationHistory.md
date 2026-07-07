---
title: ConversationHistory
type: entity
tags: [sdk, conversation, history, persistence]
created: 2026-07-07
updated: 2026-07-07
verified_commit: 6a5625d
paths:
  - "sdk/context/_history.py"
  - "conversations/"
  - "server/message_handler.py"
---

# ConversationHistory

## Overview

`ConversationHistory` is the in-memory representation of all messages in a conversation: system, user, assistant, and tool results. It is the primary data structure passed into the agent turn loop. Its on-disk form is a JSON file in the state directory, written by `PersistenceHook` after each model call.

## Location

`sdk/context/_history.py`. Persistence helpers in `conversations/_store.py`. LRU cache management in `server/message_handler.py`.

## Details

`ConversationHistory` wraps an ordered list of message dicts (`{role, content}`). Key operations:

- `append(message)` — add a message
- `set_system_message(instruction)` — replace (or insert) the system message at position 0
- `as_list()` — return the flat message list for LLM consumption

Messages follow the OpenAI/Ollama format: `{"role": "system"|"user"|"assistant"|"tool", "content": "..."}`.

### LRU Cache

`server/message_handler.py` maintains an in-memory `OrderedDict` of up to 25 `ConversationHistory` instances, keyed by `conversation_id`. On cache miss, the history is rehydrated from disk (if it exists). On eviction, the browser session for that conversation is also released.

### Persistence

`conversations/_store.py` reads/writes `history.json` per conversation under the state directory. `conversations/__init__.py` also provides:
- `load_agent_events` / `save_agent_events` — for event replay on resume
- `load_preview_state` / `save_preview_state` — for preview panel state
- `save_conversation_title` — for generated titles
- `load_conversation_profile` / `save_conversation_profile` — which profile a conversation used

## Related Entities

- [[Turn Lifecycle]] — each turn appends to a history
- [[Context Compaction]] — operates on the history to reduce token count
- [[AgentProfile]] — system prompt comes from the profile

## Sources

- `docs/sdk_semantics.md` — Conversation and History concepts
