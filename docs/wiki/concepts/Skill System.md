---
title: Skill System
type: concept
tags: [skills, tools, dynamic-loading, prompt-injection, agent-state]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - SDK Overview]]"]
---

# Skill System

## Overview

The Skill System allows agents to progressively expand their tool set at runtime. Rather than giving every agent every tool at startup (which bloats context), skills are bundles of tools + a prompt fragment that can be attached at the profile level (always available) or loaded dynamically mid-conversation via the `load_skill` tool.

## How It Works

**Skill structure:** a `Skill` has an ID, name, description, prompt fragment, and list of tool callables.

**Baseline skills (profile-granted):**
1. `build_agent_state(profile, conversation_id)` resolves each skill ID in `profile.skills`
2. Calls `agent_state.add(skill)` for each — attached but NOT in `loaded_skill_ids` (baseline)
3. Re-derived from profile each turn so profile edits take effect without being "pinned" to old conversations

**Runtime-loaded skills:**
1. LLM calls `load_skill(name)` tool
2. `sdk.skills._tools.load_skill` resolves skill by name and calls `agent_state.load(skill)`
3. Skill added to `loaded_skill_ids` (the cross-turn delta)
4. Prompt fragment immediately injected into system message via `LoadedSkillHook`

**Cross-turn persistence:**
1. At turn end: `persist_loaded_skills(agent_state, conversation_id)` saves `loaded_skill_ids` to `conversations/{id}/loaded_skills.json`
2. On next turn: `build_agent_state` restores these via `load_loaded_skills(conversation_id)` → `agent_state.load(skill)`

**Prompt injection:** `AgentState.build_skill_prompt()` formats all loaded skill prompts as:
```
── Loaded Skills ──

### SkillName
{skill prompt fragment}
```
The `LoadedSkillHook` injects this into the system message at `before_model`.

**Tool catalog:** `list_available_skills()` lists all skills not yet loaded — gives the model discovery capability

## Key Details

- Deduplication by `__name__` prevents duplicate tools even if loaded multiple times
- The `loaded_skill_ids` delta is minimal — doesn't include the profile's baseline skills (those are always re-derived)
- Skills can contain any number of tools; the context estimator includes skill tools in its token count
- Default skills live in `sdk/skills/default_skills/`; custom skills in `tools/custom_tools/`
- `ToolCategory` provides grouping for the UI's skill catalog

## Sources

- [[Source - SDK Overview]]
