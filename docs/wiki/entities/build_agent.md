---
title: build_agent
type: entity
tags: [agent-runtime, agents, construction]
created: 2026-07-07
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "agent_runtime/_factory.py"
---

# build_agent

## Overview

`AgentFactory.build_agent()` constructs an `Agent` dataclass (the execution-local
config `agent_core` runs against — see `agent_core/agent.py`) from a saved
`AgentProfile`. This moved here from a free function in `agents/_agent_builder.py` in
the `agent_core`/`agent_runtime` split — that module no longer exists.

## Location

`agent_runtime/_factory.py`, as a `@staticmethod` on `AgentFactory`.

## Details

```python
AgentFactory.build_agent(profile: AgentProfile, *, name: str | None = None) -> Agent
```

- Raises `RuntimeError` if the profile has no `provider`/`model` configured.
- Maps profile sampling fields (`context_window`→`num_ctx`, `num_predict`,
  `temperature`, `top_k`, `top_p`, `repeat_penalty`, `reasoning_effort`,
  `reasoning_summary`, `thinking_budget`) into the provider-facing `options` dict,
  dropping any that are `None` so providers see only explicitly-set parameters.
- `name` defaults to `profile.name.upper()` — the display name shown in multi-agent UI
  (root and sub-agents alike).
- Carries `context_window`, `compaction_threshold` (default 0.75 if unset), and
  `max_iterations` (default 0 = unbounded) straight onto the `Agent`.

`build_agent` is one piece of the larger `AgentFactory.prepare()` call, which also
builds `AgentCapabilities` and resolves the LLM `Provider` — see [[Turn Lifecycle]] for
how all three come together for one run.

## Key Functions

- `AgentFactory.resolve_profile(profile_id)` — load-and-validate a profile id, raising if
  missing or unconfigured; called before `build_agent`.
- `AgentFactory.build_agent(profile, *, name=None)` — the constructor itself.
- `AgentFactory.build_capabilities(profile, *, spawn_agent, conversation_id=None, connections=())`
  — sibling method building the tool/skill/capability set for the same run.
- `AgentFactory.prepare(profile, *, spawn_agent, ...)` — calls both and resolves the
  provider, returning a `PreparedAgent`.

## Related Entities

- [[AgentProfile]] — the input
- [[Turn Lifecycle]] — where `prepare()` is called from
- [[Provider Abstraction]] — `get_provider(agent.provider)` resolves the matching `Provider`

## Sources

- `agent_runtime/_factory.py`
