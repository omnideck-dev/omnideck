---
title: AgentEvent
type: entity
tags: [agent-core, events, model]
created: 2026-07-07
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "agent_core/events/_models.py"
---

# AgentEvent

## Overview

`AgentEvent` is the envelope for every typed record a turn produces — not a UI
notification layered on top of conversation state, but the thing conversation state
*is derived from*. See [[Event System]] for the full picture of how events flow from
publication to the LLM-facing history, disk, and the UI.

## Location

`agent_core/events/_models.py`. Re-exported from `agent_core/events/__init__.py` and
`agent_core/__init__.py`.

## Details

```python
class AgentEvent(BaseModel):
    payload: AgentEventPayload   # discriminated union, see below
    id: str                       # f"evt_{uuid4().hex}", stable
    timestamp: datetime            # UTC, set at construction
    agent_name: str | None         # filled by publish_event() from context stack
    agent_id: str | None           # hierarchical context id
    depth: int | None              # 0 = root, 1+ = sub-agent nesting
```

`to_flat_dict(conversation_id)` merges envelope fields and payload fields (minus the
duplicate `type` key) into the flat dict persisted to `events.jsonl`.

### Payload union (`AgentEventPayload`)

Discriminated on `type`. As of this page's `verified_commit`:

| `type` | Payload | Carries |
|--------|---------|---------|
| `content` | `ContentPayload` | streamed/complete text + thinking; `delta` flag |
| `iteration` | `IterationPayload` | one full model iteration: thinking, content, tool calls, `stopped` flag |
| `tool_result` | `ToolResultPayload` | a tool's textual return value |
| `user_message` | `UserMessagePayload` | opening prompt or mid-turn nudge; attachments; `is_nudge` |
| `agent_started` / `agent_completed` | `AgentStartedPayload` / `AgentCompletedPayload` | agent-span lifecycle, parent/child linkage |
| `spawn_requested` | `SpawnRequestedPayload` | correlates a spawn to its child's `agent_started` |
| `compaction` | `CompactionPayload` | summarization result — see [[Context Compaction]] |
| `context_usage` | `ContextUsagePayload` | per-call token usage + fill ratio |
| `browser_screenshot` | `BrowserScreenshotPayload` | tab screenshot or tab-set reconcile |
| `file_output` | `FileOutputPayload` | a file the agent produced |
| `terminal_output` | `TerminalOutputPayload` | virtual-computer bash command running/completed |
| `generation_preview` | `GenerationPreviewPayload` | image/video generation progress |
| `audio_playback` | `AudioPlaybackPayload` | audio the agent wants played in-browser |
| `desktop_active` | `DesktopActivePayload` | desktop environment ready |
| `tool_created` | `ToolCreatedPayload` | a custom tool was created |
| `error` | `ErrorPayload` | turn failure shown to the user |
| `turn_end` | `TurnEndPayload` | root agent finished |

## Related Entities

- [[AgentProfile]] — drives the `Agent` that a turn producing these events is built from
- [[Task Engine]] — autonomous runs emit the same event types
- [[Multi-Agent Architecture]] — `agent_id`/`depth`/parent linkage come from sub-agent spawning

## Sources

- `agent_core/events/_models.py`
