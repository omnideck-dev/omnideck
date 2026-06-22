---
title: Skill
type: entity
tags: [skill, tools, prompt, dynamic-loading]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - SDK Overview]]"]
---

# Skill

## Overview

`Skill` (in `sdk/skills/_registry.py`) is a resolved bundle of tool callables and a prompt fragment. Skills are attached to agents either from their profile baseline or dynamically loaded mid-conversation. They extend the agent's capability set without requiring a new profile.

## Details

**Fields:**
- `id: str` — stable identifier; defaults to `name` if unset
- `name: str` — unique display name used in `load_skill()` calls
- `description: str` — one-line description shown in the skill catalog
- `prompt: str` — prompt fragment injected into system message when skill is loaded
- `tools: list[Any]` — callable tools granted by this skill

**Note on `tools` type:** typed `list[Any]` rather than `list[Callable]` to avoid Pydantic introspecting callable signatures via `typing.get_type_hints`, which can deadlock on the import lock when constructing tools mid-import.

**Skill catalog:** built at startup; default skills in `sdk/skills/default_skills/`; custom skills in `tools/custom_tools/`

**Lifecycle:**
1. Profile specifies skill IDs in `AgentProfile.skills`
2. `build_agent_state(profile, conversation_id)` resolves each skill ID → `Skill` and calls `agent_state.add(skill)` (baseline)
3. LLM can call `load_skill(name)` tool to dynamically add more skills → calls `agent_state.load(skill)`
4. `agent_state.build_skill_prompt()` formats all skill prompts for system message injection
5. `persist_loaded_skills(agent_state, conversation_id)` saves runtime-loaded IDs for next turn restoration

**Tool categories (`sdk/skills/_tool_categories.py`):** groups skills into categories for the UI tool catalog; `ToolCategory` model

## Related Entities

- [[AgentState]] (holds attached skills)
- [[AgentProfile]] (specifies baseline skill IDs)
- [[SkillSystem]] concept
- [[LoadedSkillHook]] (persists loaded skills)

## Sources

- [[Source - SDK Overview]]
