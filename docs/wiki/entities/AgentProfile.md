---
title: AgentProfile
type: entity
tags: [agent, profile, configuration]
created: 2026-07-07
updated: 2026-07-07
verified_commit: 6a5625d
paths:
  - "agents/_agent_profiles.py"
  - "agents/types.py"
---

# AgentProfile

## Overview

`AgentProfile` is the Pydantic model that defines an agent's full runtime configuration: model provider, model name, system prompt, inference parameters, skills, and operational limits. Profiles are stored as JSON files in the state directory and can be created, edited, duplicated, and deleted by the user.

## Location

Defined in `agents/_agent_profiles.py`. Re-exported from `agents/__init__.py`.

## Details

Key fields:

| Field | Type | Purpose |
|-------|------|---------|
| `id` | `str` | Unique identifier (slug, used as filename) |
| `name` | `str` | Display name |
| `description` | `str` | Short description shown in the UI |
| `system_prompt` | `str` | Root instruction given to the model |
| `provider` | `str \| None` | LLM provider name (e.g., `"ollama"`, `"anthropic"`) |
| `model` | `str \| None` | Model identifier |
| `skills` | `list[str]` | Skill IDs to load at turn start |
| `temperature` | `float \| None` | Sampling temperature |
| `top_k` | `int \| None` | Top-K sampling |
| `top_p` | `float \| None` | Nucleus sampling |
| `context_window` | `int \| None` | Model context window in tokens (used for compaction) |
| `compaction_threshold` | `float \| None` | Fill ratio (0.0–1.0) at which compaction fires |
| `max_iterations` | `int \| None` | Turn loop iteration cap |
| `think` | `bool \| None` | Enable chain-of-thought / thinking mode |
| `reasoning_effort` | `str \| None` | Provider-specific reasoning effort hint |
| `thinking_budget` | `int \| None` | Token budget for thinking |

## Key Functions

- `get_agent_profile(profile_id)` — load a single profile by ID from disk
- `get_default_profile()` — return the profile marked as default (or first available)
- `list_agent_profiles()` — list all profiles
- `save_agent_profile(profile)` — write profile JSON to disk
- `delete_agent_profile(profile_id)` — remove from disk
- `duplicate_agent_profile(profile_id)` — clone with a new ID
- `apply_llm_config_to_profiles(provider, model)` — bulk-update all profiles to a new provider/model (used by setup wizard)

## Related Entities

- [[build_agent]] — constructs an `Agent` from a profile
- [[AgentEvent]] — events emitted during a turn driven by a profile
- [[Task Engine]] — autonomous tasks reference a profile ID

## Sources

- `agents/_agent_profiles.py`
