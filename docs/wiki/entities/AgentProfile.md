---
title: AgentProfile
type: entity
tags: [agent, profile, configuration, pydantic]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - Agents Overview]]", "[[Source - README.md]]"]
---

# AgentProfile

## Overview

`AgentProfile` is a Pydantic model in `agents/_agent_profiles.py` that represents a reusable agent configuration. It bundles together a model+provider selection, system prompt, skill list, and inference parameters. Profiles are persisted as JSON files and loaded fresh from disk on every access. The setup wizard stamps the chosen model/provider onto blank profiles at first run.

## Details

**Storage:** `{home_dir}/agent_profiles/{id}.json`

**Key fields:**
- `id: str` — stable identifier; "omnideck" is always sorted first in listings
- `name: str` — display name
- `description: str` — one-line description
- `enabled: bool` — disabled profiles are filtered from normal listings
- `system_prompt: str` — the agent's base instruction; memory is prepended at turn time
- `provider: str` — which provider (e.g., "anthropic", "openai", "ollama")
- `model: str` — model identifier
- `skills: list[str]` — list of skill IDs to attach at baseline
- `allow_spawn: bool` — whether this agent can spawn sub-agents
- `allow_load_skills: bool` — whether this agent can load additional skills mid-conversation

**Inference parameters:** `temperature`, `top_k`, `top_p`, `repeat_penalty`, `num_predict`, `think`, `reasoning_effort`, `reasoning_summary`, `thinking_budget`, `context_window`, `compaction_threshold`, `max_iterations`

**Registry functions:**
- `list_agent_profiles(include_disabled=False)` — sorted list; "omnideck" first
- `get_agent_profile(profile_id)` → `AgentProfile | None`
- `get_default_profile()` — reads `default_agent` from settings
- `save_agent_profile(profile)` — writes JSON to disk
- `delete_agent_profile(profile_id)` → bool
- `duplicate_agent_profile(profile_id, new_name=None)` → new AgentProfile with new hex ID
- `apply_llm_config_to_profiles(model, provider, context_window)` — setup wizard stamp

## Related Entities

- [[AgentBuilder]] (creates [[Agent]] from profile)
- [[Agent]] (runtime representation)
- [[AgentState]] (built from profile's skills)
- [[Skill]] (referenced by skills list)
- [[Settings]] (provides `default_agent`)
- [[ContextManager]] (uses `compaction_threshold` from profile)

## Sources

- [[Source - Agents Overview]]
- [[Source - README.md]]
- [[Source - Server Overview]]
