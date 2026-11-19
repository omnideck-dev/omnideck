---
title: Multi-Agent Architecture
type: concept
tags: [agent-runtime, agent-core, sub-agents, spawn]
created: 2026-10-18
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "agent_runtime/_spawn.py"
  - "agent_runtime/_session.py"
  - "agent_runtime/_runner.py"
  - "agent_core/events/_context.py"
---

# Multi-Agent Architecture

## Overview

An agent can delegate a subtask to a **sub-agent**: a nested turn running its own
profile, its own context window, and its own tool loop, reporting a text summary back
to the parent when done. Sub-agents can nest arbitrarily (a sub-agent can itself spawn
sub-agents), and every execution in the tree is tracked by a hierarchical
`execution_id` so events, token usage, and stop/nudge signals can be attributed and
targeted precisely. This is distinct from **multi-agent instances** — separate
work/home/project contexts with their own isolated profiles/configs/tool access —
which is a deployment/configuration concept rather than something implemented inside a
single turn; this page covers only the in-turn sub-agent mechanism.

## How It Works

### The tool the model sees

`agent_runtime/_spawn.py`'s `make_spawn_tool(invoke)` builds a `spawn_agent(instructions,
profile, agent_name="SUB_AGENT")` tool bound to a specific parent execution via a closure
— the model never passes runtime identity as an argument, only the task. It's added to
an agent's tool list by `AgentFactory._base_tools()` only when the profile's
`allow_spawn` is true (see [[AgentProfile]]), alongside `list_agent_profiles` so the
model can discover what profiles exist to delegate to.

### Spawning a child

Calling `spawn_agent` invokes `AgentRunner._invoke_child()`
(`agent_runtime/_runner.py`):
1. `session.require_parent(parent)` verifies the call is happening inside the execution
   that owns this spawn tool — a safety check against a stale closure being invoked from
   the wrong context.
2. Resolves the target `AgentProfile` by id; refuses if not found or `enabled=False`.
3. `session.create_child(parent)` (`agent_runtime/_session.py`) allocates a new
   `ExecutionContext` whose `execution_id` is `f"{parent.execution_id}.agent.{uuid4().hex}"`
   — dot-separated ancestry baked into the id itself — and whose `ancestors` tuple
   records every ancestor's `(execution_id, agent_name)` pair.
4. `AgentRunner.execute()` runs recursively for the child, with a child-specific
   `RunPolicy` (`_CHILD_POLICY`: no skill restore/persist, no memory injection — those
   are root-only concerns) and a fresh `correlation_id` (a UUID shared between the
   parent's `SpawnRequestedPayload` and the child's `AgentStartedPayload`, letting the UI
   anchor a spawn card to its originating call).
5. The child gets its own `ConversationHistory` scoped to its `execution_id`
   (`history = ConversationHistory(conversation_id=..., agent_id=context.execution_id)`),
   subscribed to the same `RunSession` so its events flow through the same disk/UI
   writers and sequence numbering as the root's.
6. On completion, `result.raise_for_status()` propagates a child error/stop up to the
   caller as an exception from the `spawn_agent` tool call — the parent sees a tool
   result either way (the return text on success, or the tool-dispatch layer's error
   formatting on failure).

### Attribution and nesting depth

`agent_span()` (`agent_core/events/_context.py`) pushes `(context_id, agent_name)` onto
a `ContextVar`-held stack for the duration of each execution; `depth` on every
`AgentEvent` is `len(stack) - 1`, so root = 0 and each spawn level adds 1. This is what
lets the UI render a nested card tree purely from the flat event stream, with no
separate "tree" data structure.

### Stop and nudge propagation

A child's `ExecutionControl` shares the same `stop_event` as the parent's (set in
`create_child`), so stopping a run stops every sub-agent beneath it too. Nudges, by
contrast, are per-execution: `RunHandle.nudge(message, execution_id=...)` targets one
specific execution in the tree, so a user (or the app) can nudge a running sub-agent
without disturbing its parent or siblings.

### Token usage rollup

`RunSession.finish()` sums `TokenUsage` across `self._results` — every execution's
`ExecutionResult.usage`, root and every completed child — into one `RunResult.usage` for
the whole run.

## Where It Lives

| File | Role |
|------|------|
| `agent_runtime/_spawn.py` | `make_spawn_tool()` — the model-facing `spawn_agent` tool |
| `agent_runtime/_runner.py` | `AgentRunner._invoke_child()`, `.execute()` recursion |
| `agent_runtime/_session.py` | `RunSession.create_child()` — ancestry, per-child history |
| `agent_core/events/_context.py` | `agent_span()` — attribution stack, depth |
| `agents/_list_profiles_tool.py` | `list_agent_profiles` tool the spawning model uses to discover targets |

## Key Details

- **A sub-agent has zero implicit context from its parent.** `spawn_agent`'s docstring
  tells the calling model to make `instructions` fully self-contained — the child's
  `ConversationHistory` starts empty except for its own system prompt.
- **Sequential, not parallel, by default.** Spawning several sub-agents happens via
  separate `spawn_agent` calls; execution is awaited per call unless the model issues
  multiple tool calls in one iteration and `parallel.enabled` is on (see
  [[Turn Lifecycle]]) — most profiles run tool calls one at a time.
- **Disabled profiles can't be spawned into**, even if the model knows their id —
  `_invoke_child` checks `enabled` explicitly, independent of whether `list_agent_profiles`
  would have surfaced it.

## Open Questions

- Where "multi-agent instances" (work/home/projects, isolated contexts) are actually
  implemented — this looks like a deployment-level concern (separate containers/data
  dirs) rather than code in `agent_runtime`/`agent_core`; not confirmed in this pass.

## Sources

- None beyond source code for this pass.
