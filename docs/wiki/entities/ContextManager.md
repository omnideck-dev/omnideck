---
title: ContextManager
type: entity
tags: [context, compaction, token-estimation, strategies]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - SDK Overview]]"]
---

# ContextManager

## Overview

`ContextManager` (in `sdk/context/_manager.py`) orchestrates context window management for a single agent scope. It holds references to `ConversationHistory` and `AgentState`, estimates token usage, publishes `ContextUsagePayload` events after each model call, and runs pluggable `ContextStrategy` objects at trigger points.

## Details

**Constructor:**
```
ContextManager(
    history, agent_state, context_limit,
    strategies=None, agent_name="", compaction_threshold=0.75
)
```

**Key methods:**
- `stats` property — computes `ContextStats(context_used, context_limit)` on demand; uses `estimate_tokens(history.messages, tools=agent_state.tools)`
- `after_model(iteration, max_iterations)` — publishes `ContextUsagePayload`; runs `AFTER_MODEL_CALL` strategies
- `before_model()` — runs `BEFORE_MODEL_CALL` strategies

**Token estimation:** `estimate_tokens()` in `sdk/context/_estimator.py` approximates tokens from characters (`chars / 4`); includes tools in the estimate

**Strategy interface:**
```python
class ContextStrategy(Protocol):
    trigger: TriggerPoint
    def should_apply(history, stats) -> bool
    async def apply(history, stats) -> None
```

**`TriggerPoint`:** `BEFORE_MODEL_CALL` or `AFTER_MODEL_CALL`

**`LLMCompactionStrategy`:** the main strategy; triggers `BEFORE_MODEL_CALL` when `fill_ratio >= threshold`; see [[LLMCompactionStrategy]] for full details

**Debug visualization:** when `DEBUG` logging enabled, prints a colored bar showing context fill percentage to stderr

**Usage in message_handler:**
```python
ctx_manager = ContextManager(history, agent_state, context_limit=agent.context_window, ...)
```
The `ContextHook` calls `ctx_manager.after_model()` and `ctx_manager.before_model()` at the appropriate hook phases.

## Related Entities

- [[ConversationHistory]]
- [[AgentState]]
- [[LLMCompactionStrategy]]
- [[ContextHook]]
- [[ContextUsagePayload]]
- [[AgentEvent]]

## Sources

- [[Source - SDK Overview]]
