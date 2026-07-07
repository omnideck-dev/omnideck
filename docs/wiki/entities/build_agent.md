---
title: build_agent
type: entity
tags: [agent, factory, profile]
created: 2026-07-07
updated: 2026-07-07
verified_commit: 6a5625d
paths:
  - "agents/_agent_builder.py"
  - "agents/types.py"
---

# build_agent

## Overview

`build_agent(profile, tools, *, name=None)` is the factory function that constructs an `Agent` dataclass from an `AgentProfile` and a list of tool callables. It's the only sanctioned way to instantiate an `Agent`.

## Location

`agents/_agent_builder.py`. Re-exported from `agents/__init__.py`.

## Details

```python
def build_agent(
    profile: AgentProfile,
    tools: list[Callable[..., Any]],
    *,
    name: str | None = None,
) -> Agent:
```

Raises `RuntimeError` if the profile has no `provider` or `model` configured (e.g., setup wizard not yet completed).

Constructs the `Agent` dataclass (`agents/types.py`) with:
- `name` — defaults to `profile.name.upper()`
- `instruction` — `profile.system_prompt`
- `provider`, `model` — from profile
- `options` — inference parameters (temperature, context window, etc.), with `None` values filtered out
- `tools` — the provided callable list
- `think`, `context_window`, `compaction_threshold`, `max_iterations` — from profile

The `Agent` dataclass is what `run_turn()` consumes directly.

### `Agent` dataclass

```python
class Agent(BaseModel):
    name: str
    description: str
    instruction: str          # system prompt
    provider: str
    model: str
    options: dict[str, Any]   # inference params
    tools: list[Callable]
    think: bool = False
    context_window: int = 0
    compaction_threshold: float = 0.75
    max_iterations: int = 0
```

## Related Entities

- [[AgentProfile]] — source of all configuration
- [[Turn Lifecycle]] — `build_agent` output is passed to `run_turn()`

## Sources

- `agents/_agent_builder.py`
