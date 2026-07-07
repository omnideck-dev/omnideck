---
title: AgentEvent
type: entity
tags: [sdk, events, streaming]
created: 2026-07-07
updated: 2026-07-07
verified_commit: 6a5625d
paths:
  - "sdk/events/_models.py"
  - "sdk/events/__init__.py"
---

# AgentEvent

## Overview

`AgentEvent` is the top-level event envelope emitted during a turn. It wraps a single typed `AgentEventPayload` and carries shared metadata (agent attribution, timestamp, depth). The entire agent-to-UI communication is expressed as a stream of `AgentEvent` objects serialized as JSONL.

## Location

Defined in `sdk/events/_models.py`. Re-exported from `sdk/events/__init__.py`.

## Details

```python
class AgentEvent(BaseModel):
    payload: AgentEventPayload   # discriminated union, keyed on payload.type
    timestamp: datetime          # UTC creation time
    agent_name: str | None       # emitting agent's name
    agent_id: str | None         # hierarchical dot-notation context id
    depth: int | None            # nesting depth (0 = root)
```

`AgentEventPayload` is a discriminated union selecting one of:

| `type` value | Payload class | Purpose |
|---|---|---|
| `content` | `ContentPayload` | LLM text delta or complete chunk |
| `turn_end` | `TurnEndPayload` | Root agent finished |
| `tool_call` | `ToolCallPayload` | Tool invocation notification |
| `browser_screenshot` | `BrowserScreenshotPayload` | Viewport capture |
| `file_output` | `FileOutputPayload` | File produced in virtual computer |
| `terminal_output` | `TerminalOutputPayload` | Bash command start/end |
| `context_usage` | `ContextUsagePayload` | Token fill ratio after each LLM call |
| `agent_started` | `AgentStartedPayload` | Agent span opened |
| `agent_completed` | `AgentCompletedPayload` | Agent span closed |
| `spawn_requested` | `SpawnRequestedPayload` | Sub-agent spawn initiated |
| `generation_preview` | `GenerationPreviewPayload` | Image/video progress |
| `audio_playback` | `AudioPlaybackPayload` | Base64 audio to play in browser |
| `desktop_active` | `DesktopActivePayload` | Desktop environment started |
| `tool_created` | `ToolCreatedPayload` | New custom tool created |

## Related Entities

- [[Event System]] — how events flow from agent to UI
- [[AgentProfile]] — the profile whose turn emitted the event

## Sources

- `sdk/events/_models.py`
