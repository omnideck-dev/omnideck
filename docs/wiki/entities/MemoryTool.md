---
title: MemoryTool
type: entity
tags: [memory, persistence, key-value, tools]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - Tools Overview]]"]
---

# MemoryTool

## Overview

The memory tools (in `tools/memory/memory.py`) provide simple, persistent key-value storage for the agent. Memories survive across conversations and container restarts. They are injected into the system message at the start of each turn so the agent always has access to them.

## Details

**Storage:** `{home_dir}/memory.json` — JSON file with atomic writes (temp file + rename)

**Format:** `{"key": {"value": "...", "hidden": false}}`

**LLM-callable tools:**
- `remember(key, value)` — stores a persistent memory; preserves existing hidden state on update
- `forget(key)` — removes a key; returns `{status: "not_found"}` if missing

**API functions (not LLM tools):**
- `load_memory()` → `dict[str, MemoryEntry]`
- `set_key_hidden(key, hidden)` — toggle visibility in the UI

**System message injection:** `_refresh_system_message()` in `message_handler.py` prepends a formatted memory block to the system prompt before each model call

**Hidden keys:** keys marked `hidden=True` are not shown in the UI but ARE included in the system message (the agent still knows about them)

**Atomic writes:** uses `tempfile.NamedTemporaryFile` + `Path.replace()` for crash-safe writes

## Related Entities

- [[ConversationHistory]] (memory injected into system message each turn)
- [[MessageHandler]] (calls `load_memory` and `_refresh_system_message`)
- [[Settings]] (home_dir path)

## Sources

- [[Source - Tools Overview]]
