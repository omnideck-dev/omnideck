---
title: Turn Lifecycle
type: concept
tags: [agent-core, agent-runtime, turn, hooks, streaming]
created: 2026-07-07
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "agent_core/turn/"
  - "agent_core/hooks/"
  - "agent_runtime/_runner.py"
  - "agent_runtime/_session.py"
  - "agent_runtime/_runtime.py"
  - "server/_agent_run_routes.py"
---

# Turn Lifecycle

## Overview

A **turn** is one root-agent invocation: an LLM-call → tool-execution loop that keeps
going until the model stops requesting tools (or a stop/budget condition fires). A turn
may spawn **sub-agents**, each running its own nested tool loop (see
[[Multi-Agent Architecture]]).

This page describes the current architecture, which replaced the old `sdk/` package
(now empty and unimported — see [[Provider Abstraction]] for the paths that moved). The
previous wiki described `sdk/turn/run_turn()` and `server/message_handler.py`; neither
exists anymore. The loop itself (`AgentExecutor`) is unchanged in spirit but the
surrounding orchestration (`AgentRuntime` → `RunSession` → `AgentRunner`) is new.

## How It Works

### 1. HTTP request arrives

A chat route in `server/_agent_run_routes.py` builds an `AgentRunRequest`
(`agent_runtime/_models.py`) — conversation id, message text, attachments, profile id,
and a `RunPolicy` — and calls `AgentRuntime.start(request)`.

### 2. Run admission

`AgentRuntime.start()` (`agent_runtime/_runtime.py`) rejects a second concurrent run for
the same `conversation_id` (`RunConflictError`), then creates a `RunSession` and
schedules `_drive(session)` as a background `asyncio.Task`. It returns a `RunHandle`
immediately — the caller awaits events/completion through the handle, not the task.

### 3. Session setup

`RunSession.__aenter__` (`agent_runtime/_session.py`) acquires the conversation's
`ConversationScope` from the `ConversationStore`, grabs its `ConversationHistory`, and
subscribes disk/UI writers (`EventsLogWriter`, `BrowserTabsWriter`, `TerminalWriter`,
`ArtifactsIndexWriter`) plus its own `_record` method, which assigns each event a
monotonic sequence number for resumable SSE replay (`RunHandle.events(after_seq)`).

### 4. Agent preparation

`AgentRunner.run()` resolves the `AgentProfile`, then `AgentRunner.execute()` calls
`AgentFactory.prepare()` (`agent_runtime/_factory.py`), which:
- builds an `Agent` dataclass (model, options, context window, etc.) via
  `AgentFactory.build_agent()` — see [[build_agent]]
- builds `AgentCapabilities` — base tools, granted capabilities, and the profile's
  skills (see [[Skill System]])
- resolves the LLM `Provider` via `providers.get_provider()` (see
  [[Provider Abstraction]])
- prepends persisted memory to the instruction, if requested

### 5. Hook composition

`default_hooks()` (`agent_core/hooks/_default.py`) assembles the standard chain — see
[[Hooks System]] for what each one does. `AgentRunner` appends an application-level
`ScratchpadHook` (Rich console logging for scratchpad reads/writes) on top.

### 6. `AgentExecutor.execute()`

`agent_core/turn/_execution.py` drives the actual loop:
1. `on_turn_start` hooks fire.
2. Each iteration: `check_stop()` → `before_model` hooks → stream the provider call via
   `chat_stream()` (publishing `ContentPayload` deltas as they arrive) → `after_model`
   hooks (each may rewrite the response) → publish an `IterationPayload` bundling
   thinking/content/tool calls for that iteration.
3. If the response has no tool calls, the loop returns an `ExecutionResult("success", …)`.
4. Otherwise each tool call runs through `_run_tool_with_hooks()` (`before_tool` /
   `after_tool`), optionally in parallel (`max_parallel_tools` from
   `config.yaml`'s `parallel` section), and the loop repeats.
5. A `StopRequestedError` or unhandled exception persists whatever already streamed as
   a partial `IterationPayload` (`stopped=True`) before returning a `"stopped"` or
   `"error"` result.
6. `on_turn_end` hooks fire in the `finally` block regardless of outcome.

### 7. Event streaming

Every hook and tool publishes `AgentEvent`s via `agent_core.events.publish_event()`.
These flow into the `RunSession`'s subscribed observers (disk writers, the UI's SSE
bridge) and into `RunSession._record()`, which is what `RunHandle.events()` replays. See
[[Event System]].

### 8. Completion

`AgentRuntime._drive()` awaits `AgentRunner.run()`, converts any exception into an
`ErrorPayload` + `ExecutionResult("error", …)`, and calls `session.finish(root)`, which
sums token usage across the whole execution tree (root + every sub-agent) into a
`RunResult`.

## Where It Lives

| File | Role |
|------|------|
| `server/_agent_run_routes.py` | HTTP entry point; builds `AgentRunRequest` |
| `agent_runtime/_runtime.py` | `AgentRuntime` — run admission, task ownership, `RunHandle` |
| `agent_runtime/_session.py` | `RunSession` — history wiring, event sequencing, child execution contexts |
| `agent_runtime/_runner.py` | `AgentRunner` — profile → prepared agent → `AgentExecutor` |
| `agent_runtime/_factory.py` | `AgentFactory` — builds `Agent`, `AgentCapabilities`, resolves provider |
| `agent_core/turn/_execution.py` | `AgentExecutor` — the iterate/call/tool-dispatch loop |
| `agent_core/turn/_turn.py` | `turn_scope()`, `check_stop()` for standalone (non-runtime) callers |
| `agent_core/hooks/_default.py` | `default_hooks()` factory |
| `agent_core/events/_context.py` | `agent_span()`, `publish_event()` |

## Key Details

- **Conversation isolation:** `AgentRuntime` refuses a second run for a conversation
  already active (`RunConflictError`); callers either wait or stop the existing run.
- **Stop signal:** `RunHandle.stop()` sets the session's `asyncio.Event`. `StopHook`
  (and `check_stop()` calls sprinkled through the executor) raise `StopRequestedError`
  at safe checkpoints — before a model call, mid-stream after each delta, and around
  tool dispatch.
- **Nudge:** `RunHandle.nudge(message, execution_id=...)` queues a message into a
  specific execution's `ExecutionControl`. `NudgeHook` splices it into history before
  the next model call. Targeting by `execution_id` lets a nudge reach a running
  sub-agent, not just the root.
- **Sub-agents:** `spawn_agent` (built per-run by `make_spawn_tool()` in
  `agent_runtime/_spawn.py`) calls back into `AgentRunner.execute()` with a child
  `ExecutionContext` from `RunSession.create_child()`. See
  [[Multi-Agent Architecture]].
- **Resumable streaming:** every published event gets a sequence number scoped to the
  run (`SequencedEvent`). A client can reconnect mid-turn and resume from
  `RunHandle.events(after_seq)` without missing or duplicating events.
- **Token usage:** `RunResult.usage` aggregates `TokenUsage` across the root execution
  and every completed sub-agent execution (`RunSession._results`).

## Open Questions

- Whether `config.yaml`'s `parallel.enabled` sees real-world use beyond tests — multiple
  tool calls in one iteration run concurrently when enabled, but most profiles ship with
  it off.

## Sources

- `docs/sdk_semantics.md` may still describe the pre-refactor model; verify before
  citing it for the current architecture.
