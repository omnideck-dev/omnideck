---
title: AgentProfile
type: entity
tags: [agents, profile, configuration]
created: 2026-07-07
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "agents/_agent_profiles.py"
  - "agents/types.py"
---

# AgentProfile

## Overview

`AgentProfile` is the Pydantic model defining an agent's full runtime configuration:
model/provider, system prompt, skills, inference parameters, and a few per-profile
feature toggles. Profiles are stored as individual JSON files under
`<home_dir>/agent_profiles/`. The user creates, edits, duplicates, and deletes them from
the Agents settings tab.

## Location

Defined in `agents/_agent_profiles.py`. Re-exported from `agents/__init__.py`.

## Details

| Field | Type | Purpose |
|-------|------|---------|
| `id` | `str` | Unique identifier (filename stem) |
| `name` | `str` | Display name |
| `description` | `str` | Shown in the UI |
| `enabled` | `bool` | Disabled profiles are hidden from pickers and can't be spawned into |
| `system_prompt` | `str` | Root instruction |
| `provider` | `str` | LLM provider name (`"ollama"`, `"anthropic"`, `"openai"`, `"openai_compat"`, `"openrouter"`) |
| `model` | `str` | Model identifier |
| `skills` | `list[str]` | Skill IDs attached at turn start — see [[Skill System]] |
| `browser_profile_id` | `str \| None` | Grants the browser capability bound to a specific browser profile |
| `allow_spawn` | `bool` | Whether this agent can call `spawn_agent` — see [[Multi-Agent Architecture]] |
| `allow_load_skills` | `bool` | Whether this agent can call `load_skill`/`list_available_skills` mid-conversation |
| `temperature`, `top_k`, `top_p`, `repeat_penalty`, `num_predict` | numeric, optional | Sampling parameters passed to the provider |
| `think` | `bool \| None` | Enable chain-of-thought mode |
| `reasoning_effort`, `reasoning_summary`, `thinking_budget` | optional | Provider-specific reasoning hints |
| `context_window` | `int \| None` | Model's context window in tokens — compaction denominator |
| `compaction_threshold` | `float \| None` | Fill ratio (0.0–1.0) at which compaction fires (default 0.75) |
| `max_iterations` | `int \| None` | Turn-loop iteration cap |

`OMNIDECK_ID = "omnideck"` is a reserved profile id that always sorts first in listings
when present — the shipped default profile.

## Key Functions

- `get_agent_profile(profile_id)` — load a single profile by ID
- `get_default_profile()` — the profile named by the `default_agent` setting
- `list_agent_profiles(include_disabled=False)` — Omnideck profile first, then others
  sorted by name; filters disabled profiles unless asked not to
- `save_agent_profile(profile)` — write profile JSON to disk
- `delete_agent_profile(profile_id)` — remove from disk, returns `False` if not found
- `duplicate_agent_profile(profile_id, new_name=None)` — clone with a fresh id
- `apply_llm_config_to_profiles(model, *, provider=None, context_window=None)` —
  stamp a model onto every profile that doesn't already have one (used by the setup
  wizard's finish step; per-profile edits after that go through the normal save path)

## Related Entities

- [[build_agent]] — `AgentFactory.build_agent()` constructs an `Agent` from a profile
- [[AgentEvent]] — events emitted during a turn driven by a profile
- [[Task Engine]] — routines reference a profile ID
- [[Multi-Agent Architecture]] — `spawn_agent` resolves a profile by id for the child

## Sources

- `agents/_agent_profiles.py`
