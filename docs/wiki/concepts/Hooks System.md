---
title: Hooks System
type: concept
tags: [agent-core, hooks, turn]
created: 2026-07-07
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "agent_core/hooks/"
  - "agent_runtime/_scratchpad_hook.py"
---

# Hooks System

## Overview

A hook is a plain object implementing one or more of six optional phase methods. The
executor checks for each method with `getattr(hook, name, None)` rather than requiring
inheritance from a base class — a hook only needs the phases it actually uses. This lets
cross-cutting concerns (budget limits, loop detection, context compaction, logging)
compose onto the turn loop without the loop itself knowing about any of them.

## How It Works

### The contract

`agent_core/hooks/_types.py` defines six `Protocol` classes, unioned into a `Hook`
type alias:

| Phase | Signature | When |
|-------|-----------|------|
| `on_turn_start` | `(agent_name) -> None` | Once, before the first iteration |
| `before_model` | `async (history, iteration, agent_name) -> None` | Before each LLM call |
| `after_model` | `async (response, history, iteration, agent_name) -> ChatResponse` | After each LLM call — can rewrite the response |
| `before_tool` | `(tool_name, tool_arguments) -> str \| None` | Before a tool executes — returning non-`None` *skips* execution and substitutes the return value as the result |
| `after_tool` | `(tool_name, tool_arguments, tool_result) -> str` | After a tool executes — can rewrite the result |
| `on_turn_end` | `(final_content, agent_name) -> None` | Once, in a `finally` block, regardless of outcome |

### The standard chain

`default_hooks(agent, *, max_iterations=0, ctx_manager=None)`
(`agent_core/hooks/_default.py`) assembles, in order:

1. **`NudgeHook`** — drains any queued nudge messages (from
   `ExecutionControl.nudges`, via `_current_control`) and splices them into history
   before the next model call.
2. **`StopHook`** — calls `check_stop()` at `before_model` and `after_model`; raises
   `StopRequestedError` if a stop was requested.
3. **`BudgetGuard`** *(only if `max_iterations > 0`)* — publishes a user-shaped nudge
   warning when the iteration budget is exceeded.
4. **`LoopDetector`** — hashes each round's tool-call signature; after a configurable
   number of identical consecutive rounds (default threshold 10), publishes a nudge
   telling the model it's repeating itself.
5. **`LoggingHook`** — renders Rich console panels/tables of model input and output for
   local dev visibility. Not shipped to the UI.
6. **`LoadedSkillHook`** — reads `AgentCapabilities` (via
   `get_active_agent_capabilities()`) and appends a formatted "Capabilities & Skills"
   section to the system message before every call, replacing the previous one each
   time so it always reflects what's currently loaded.
7. **`ToolResultCapHook`** — spills oversized tool results to a temp file and replaces
   the in-context copy with a truncated placeholder, so one huge tool result can't blow
   the context budget on its own.
8. **`ContextHook`** *(only if `ctx_manager` is supplied)* — delegates `before_model`/
   `after_model` to the `ContextManager`, which runs `ContextStrategy` instances (e.g.
   `LLMCompactionStrategy`) and publishes `ContextUsagePayload`. See
   [[Context Compaction]].

`AgentRunner.execute()` (`agent_runtime/_runner.py`) appends one more hook that
`default_hooks()` doesn't know about: **`ScratchpadHook`**
(`agent_runtime/_scratchpad_hook.py`) — an application-level hook that logs a Rich panel
whenever the agent reads or writes its scratchpad. It lives in `agent_runtime` rather
than `agent_core/hooks` because it's cosmetic/app-specific, not a core execution concern.

### Dispatch

`AgentExecutor._execute()` (`agent_core/turn/_execution.py`) iterates the hook list at
each phase, calling whichever ones implement it. `after_model` hooks chain: each one
receives the previous hook's (possibly rewritten) response and returns its own. The
dispatch loop has no special-casing per hook type — any object satisfying one of the six
protocols works.

## Where It Lives

| File | Role |
|------|------|
| `agent_core/hooks/_types.py` | The six-phase `Hook` protocol union |
| `agent_core/hooks/_default.py` | `default_hooks()` factory |
| `agent_core/hooks/_nudge_hook.py` | `NudgeHook` |
| `agent_core/hooks/_stop_hook.py` | `StopHook` |
| `agent_core/hooks/_budget_guard.py` | `BudgetGuard` |
| `agent_core/hooks/_loop_detector.py` | `LoopDetector` |
| `agent_core/hooks/_logging_hook.py` | `LoggingHook` |
| `agent_core/hooks/_loaded_skill_hook.py` | `LoadedSkillHook` |
| `agent_core/hooks/_result_cap.py` | `ToolResultCapHook` |
| `agent_core/hooks/_context_hook.py` | `ContextHook` |
| `agent_runtime/_scratchpad_hook.py` | `ScratchpadHook` (application-level, not in the default chain) |

## Key Details

- **Structural, not inherited.** A new hook needs no base class — just implement the
  phase methods it cares about. `AgentExecutor` discovers them via `getattr(..., None)`.
- **`before_tool` can short-circuit.** Returning a non-`None` string from `before_tool`
  skips the actual tool call entirely and uses that string as the result — not currently
  used by any shipped hook, but the mechanism exists (e.g. for a future approval gate).
- **`after_model` hooks can rewrite, not just observe.** `StopHook`'s `after_model`
  strips tool calls and raises if a stop landed between the call starting and the
  response arriving.
- **PersistenceHook doesn't exist as a hook anymore.** Disk persistence of events is now
  handled by observers subscribed directly to `ConversationHistory` (`EventsLogWriter`
  et al. — see [[Event System]]), not by a turn-loop hook phase.

## Open Questions

- None identified this pass.

## Sources

- None beyond source code for this pass.
