---
title: PersistenceHook
type: entity
tags: [hook, persistence, conversation, history]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - SDK Overview]]"]
---

# PersistenceHook

## Overview

`PersistenceHook` (in `sdk/hooks/_persistence.py`) implements `on_turn_end` to save conversation history to disk when a turn completes. For sub-agents, it writes to a separate sub-agent history file rather than overwriting the main conversation.

## Details

**Constructor:**
```python
PersistenceHook(conversation_id, history, sub_agent_name=None, sub_agent_id=None)
```

**`on_turn_end(final_content, agent_name)`:**
- If sub-agent: calls `save_sub_agent_history(conversation_id, sub_agent_name, sub_agent_id, history.non_system_messages)`
- Otherwise: calls `save_conversation_history(conversation_id, history.non_system_messages)`
- Only `non_system_messages` are persisted (system message is rebuilt each turn from profile + memory)

**Error handling:** logs exception but does not re-raise (failure to persist doesn't abort the turn)

**Lifecycle:** added to the hooks list in `message_handler._run_turn()` after `default_hooks()`

## Related Entities

- [[ConversationHistory]] (source of messages to persist)
- [[Hook System]] concept
- [[MessageHandler]]

## Sources

- [[Source - SDK Overview]]
