---
title: "Source - Agents Overview"
type: source
tags: [agents, profiles, builder, types]
created: 2026-06-22
updated: 2026-06-22
sources: []
---

# Source - Agents Overview

## Summary

The `agents/` package provides agent profile management and the `build_agent` factory. An `AgentProfile` is a JSON-persisted, reusable configuration bundling model, system prompt, skills, and inference parameters. `build_agent` takes a profile and a tool list and returns a fully configured `Agent` object. The profile registry loads from a directory of JSON files, with the built-in "omnideck" profile always sorted first.

## Key Points

**AgentProfile (`agents/_agent_profiles.py`):**
- Fields: `id`, `name`, `description`, `enabled`, `system_prompt`, `provider`, `model`, `skills` (list of skill IDs), `allow_spawn`, `allow_load_skills`
- Inference params: `temperature`, `top_k`, `top_p`, `repeat_penalty`, `num_predict`, `think`, `reasoning_effort`, `reasoning_summary`, `thinking_budget`, `context_window`, `compaction_threshold`, `max_iterations`
- Stored as JSON files in `{home_dir}/agent_profiles/{id}.json`
- "omnideck" profile ID is always sorted first in listings
- `apply_llm_config_to_profiles()` stamps model/provider onto profiles with empty model — used by setup wizard
- Default profiles ship with empty `provider`/`model`; wizard fills them in

**Agent type (`agents/types.py`):**
- `Agent` Pydantic model: `name`, `description`, `instruction`, `provider`, `model`, `options` (dict), `tools` (list of callables), `think`, `context_window`, `compaction_threshold`, `max_iterations`
- `Data` model: base64-encoded attachment with content_type and optional filename

**AgentBuilder (`agents/_agent_builder.py`):**
- `build_agent(profile, tools, name=None)` constructs `Agent` from profile
- Strips None values from raw_options before passing to Agent
- Raises RuntimeError if profile has no provider/model configured

## Entities Mentioned

- [[AgentProfile]]
- [[AgentBuilder]]
- [[Agent]]
- [[Skill]]
- [[AgentState]]

## Concepts Covered

- [[Agent Loop]]
- [[Skill System]]
- [[Provider Abstraction]]

## Raw Notes

- `PROFILES_SUBDIR = "agent_profiles"` — subdir within home_dir
- `OMNIDECK_ID = "omnideck"` — the built-in primary agent profile ID
- Profile listing: disabled profiles (`enabled=False`) filtered out by default; pass `include_disabled=True` for management UI
- `duplicate_agent_profile` generates a new 12-char hex UUID for the copy
- Profiles are loaded fresh from disk every call — no in-memory caching in the profile registry itself
- Legacy `system` field stripped on load (forward-compatibility)
