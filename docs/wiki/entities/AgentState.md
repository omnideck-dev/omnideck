---
title: AgentState
type: entity
tags: [agent, state, skills, tools, context-var]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - SDK Overview]]", "[[Source - Agents Overview]]"]
---

# AgentState

## Overview

`AgentState` (in `sdk/skills/agent_state.py`) tracks the live, mutable tool set for an active agent. It holds the base tools (from the agent's initial configuration) plus any skills loaded dynamically during the conversation. The `_active_agent_state` ContextVar stores the current scope's state so `run_turn` can access it without parameter threading.

## Details

**Construction:** `AgentState(base_tools: list[Callable])` — built by `build_agent_state(profile, conversation_id)` in `sdk/skills/_resolve.py`

**Core methods:**
- `add(skill)` — attaches a profile-granted (baseline) skill; no-op if already attached; NOT persisted cross-turn (re-derived from profile each turn)
- `load(skill)` — attaches a skill loaded at runtime; persisted in `loaded_skill_ids` for cross-turn restoration
- `tools` property — returns base tools + all skill tools, deduplicated by `__name__`
- `skill_ids` — frozenset of all attached skill IDs (profile + runtime)
- `loaded_skill_ids` — frozenset of only runtime-loaded IDs (the cross-turn delta)
- `build_skill_prompt()` — formats all skill prompts for system message injection

**Deduplication:** uses `__name__` attribute; if two tools have the same function name, only the first is included

**Context variable:** `_active_agent_state: ContextVar[AgentState | None]` — set inside `agent_span()`; read by `run_turn` at the start of each iteration

**Cross-turn persistence:**
- Profile's skills are re-attached each turn from the profile definition (no snapshot)
- Runtime-loaded skills are persisted by ID via `persist_loaded_skills(agent_state, conversation_id)` and restored via `load_loaded_skills`

## Related Entities

- [[Skill]] (attached to AgentState)
- [[AgentProfile]] (source of baseline skills)
- [[run_turn]] (reads `_active_agent_state`)
- [[agent_span]] (sets `_active_agent_state`)
- [[ContextManager]] (reads `agent_state.tools` for token estimation)
- [[LoadedSkillHook]] (persists loaded skills)

## Sources

- [[Source - SDK Overview]]
- [[Source - Agents Overview]]
