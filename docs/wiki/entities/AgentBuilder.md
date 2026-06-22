---
title: AgentBuilder
type: entity
tags: [agent, builder, factory, profile]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - Agents Overview]]"]
---

# AgentBuilder

## Overview

`build_agent` (in `agents/_agent_builder.py`) is the factory function that constructs an `Agent` runtime object from an `AgentProfile` and a tool list. It extracts inference parameters from the profile, filters out None values, and assembles the `Agent` Pydantic model.

## Details

**Signature:** `build_agent(profile: AgentProfile, tools: list[Callable], name: str | None = None) -> Agent`

**Behavior:**
- Raises `RuntimeError` if `profile.provider` or `profile.model` is empty
- Builds `raw_options` dict from all numeric/param fields on the profile
- Strips `None` values so provider doesn't receive unset params
- Name defaults to `profile.name.upper()` if not overridden

**Options mapped:**
- `num_ctx` (from `context_window`)
- `num_predict`, `temperature`, `top_k`, `top_p`, `repeat_penalty`
- `reasoning_effort`, `reasoning_summary`, `thinking_budget` (provider-specific)

**Note:** In `message_handler.py`, `build_agent` is called with `tools=[]` because tools are assembled dynamically into `AgentState` each turn — `run_turn` reads tools from `AgentState`, not from `Agent.tools` directly.

## Related Entities

- [[AgentProfile]] (input)
- [[Agent]] (output)
- [[AgentState]] (holds the actual live tools)
- [[MessageHandler]]

## Sources

- [[Source - Agents Overview]]
