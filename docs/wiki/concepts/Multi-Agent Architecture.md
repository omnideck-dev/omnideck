---
title: Multi-Agent Architecture
type: concept
tags: [multi-agent, sub-agent, spawn, hierarchy, context-var]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - SDK Overview]]", "[[Source - Server Overview]]"]
---

# Multi-Agent Architecture

## Overview

Omnideck supports hierarchical multi-agent execution where a root agent can spawn sub-agents using the `spawn_agent` tool. Sub-agents run within the same asyncio context as the parent, inherit the turn's event dispatcher and stop event via ContextVars, and have their histories persisted separately.

## How It Works

**Spawning a sub-agent:**
1. Root agent calls `spawn_agent(profile_id, instruction)` tool
2. `spawn_agent` (in `sdk/tools/_spawn_agent.py`) publishes `SpawnRequestedPayload` (with correlation_id)
3. Creates a fresh `ConversationHistory` for the sub-agent
4. Enters a nested `agent_span()` — increments depth, generates child agent_id (e.g., "root.sub1")
5. Runs `run_turn()` for the sub-agent with its own hooks (including a sub-agent `PersistenceHook`)
6. Sub-agent publishes `AgentStartedPayload` (with correlation_id matching `SpawnRequestedPayload`)
7. Sub-agent result returned to parent as tool result

**Event flow:**
- Sub-agent events inherit parent's `EventDispatcher` (same ContextVar)
- `depth` field on events distinguishes root (0) from sub-agents (1+)
- UI uses `agent_id` hierarchy and `correlation_id` to anchor sub-agent cards to their spawn point

**Context isolation:**
- Each agent_span creates its own `AgentState` and `ConversationHistory`
- Sub-agent doesn't share parent's conversation history (separate namespace)
- Stop event IS shared (stopping parent stops sub-agents too via inherited ContextVar)

**Persistence:** sub-agent history saved to `{conv_id}/sub_agents/{name}/{id}/history.json` (via `PersistenceHook` with `sub_agent_name` + `sub_agent_id` set)

**Profile resolution:** `allow_spawn` on the profile controls whether a profile can spawn sub-agents

## Key Details

- ContextVar inheritance is the mechanism: Python's ContextVar copies into child tasks at task creation time — so asyncio tasks spawned inside `agent_span` see the same dispatcher/stop event
- The `_current_depth` ContextVar increments in each nested `agent_span` so depth is tracked automatically
- Sub-agent loops are full `run_turn` loops — they have their own tool-call iterations, their own compaction (if configured), and their own hooks

## Open Questions

- Does `spawn_agent` run synchronously (parent waits) or asynchronously (parent continues)? Based on tool result flow, likely synchronous (parent waits for sub-agent result).
- Can sub-agents spawn further sub-agents? No architectural limit found, but depth tracking suggests this is anticipated.

## Sources

- [[Source - SDK Overview]]
- [[Source - Server Overview]]
