---
title: MessageHandler
type: entity
tags: [server, message-handler, conversation, turn, streaming]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - Server Overview]]"]
---

# MessageHandler

## Overview

`message_handler.py` in `server/` is the orchestration layer between the HTTP chat endpoint and the agent loop. It manages a per-process in-memory conversation cache, hydrates conversations from disk on cache miss, builds the agent from the profile, drives the turn, and streams `AgentEvent` objects back to the caller.

## Details

**Conversation cache:**
- `_conversations: OrderedDict[str, ConversationHistory]` — LRU, max 25 entries
- `_get_conversation(id)` → `(history, is_new)`: cache hit moves to end; miss loads from disk; none on disk = new conversation
- Eviction skips active turns (to prevent parallel writer conflict) and the just-inserted entry
- On eviction, calls `release_agent_browser(f"conv:{cid}")` to clean up browser state

**`handle_user_message(message, data, profile_id, conversation_id)`:**
1. Get/create `ConversationHistory` for the conversation ID
2. If attachments: write to virtual computer, append file paths to message
3. Load profile by ID; validate model is configured
4. Save profile association to conversation (for restoration)
5. Create agent via `build_agent(profile, tools=[])`
6. Start producer task that calls `_run_turn()`; feed events via `asyncio.Queue`
7. Yield events from queue until `None` sentinel

**`_run_turn()`:**
1. Build `AgentState` from profile (baseline skills + restored loaded skills)
2. Create `ContextManager` with `LLMCompactionStrategy`
3. Enter `turn_scope` with event queue handler
4. Subscribe `AgentEventBufferHook` to capture lifecycle events for persistence
5. Enter `agent_span` (sets ContextVar, publishes `AgentStartedPayload`)
6. Append user message to history
7. `_refresh_system_message` — prepend memory to system prompt
8. Build hook chain: `default_hooks()` + `PersistenceHook`
9. Call `run_turn(history, agent, hooks)`
10. On exit: persist loaded skills, save agent events, generate title (if new conversation)

**System message refresh:** called before each turn; reads `load_memory()` and prepends a formatted memory block to the profile's system prompt

**Background tasks:** title generation and loaded-skill persistence run as asyncio tasks (tracked in `_background_tasks` to prevent GC)

## Related Entities

- [[ConversationHistory]]
- [[AgentProfile]]
- [[AgentState]]
- [[ContextManager]]
- [[turn_scope]]
- [[run_turn]]
- [[PersistenceHook]]
- [[MemoryTool]]
- [[EventDispatcher]]

## Sources

- [[Source - Server Overview]]
