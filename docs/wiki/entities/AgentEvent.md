---
title: AgentEvent
type: entity
tags: [events, pydantic, payload, streaming]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - SDK Overview]]"]
---

# AgentEvent

## Overview

`AgentEvent` (in `sdk/events/_models.py`) is the top-level event envelope emitted during a turn. It carries a single discriminated-union payload plus metadata for attribution (agent name, agent ID, depth). These events are streamed as JSONL to the frontend.

## Details

**Envelope fields:**
- `payload: AgentEventPayload` — discriminated union on `type` field
- `timestamp: datetime` — UTC creation time
- `agent_name: str | None` — human-readable agent name
- `agent_id: str | None` — hierarchical context ID (e.g., "root.sub1")
- `depth: int | None` — nesting depth (0 = root, 1+ = sub-agents)

**Payload types (discriminated on `type`):**

| Type | Payload Class | Description |
|------|--------------|-------------|
| `content` | `ContentPayload` | LLM text + optional thinking; `delta=True` for streaming |
| `turn_end` | `TurnEndPayload` | Signals end of turn |
| `tool_call` | `ToolCallPayload` | Tool invocation notification (name, args) |
| `browser_screenshot` | `BrowserScreenshotPayload` | Tab URL, title, base64 PNG, tab/open tab IDs |
| `file_output` | `FileOutputPayload` | Generated file (name, MIME type, path) |
| `tool_created` | `ToolCreatedPayload` | New custom tool created |
| `audio_playback` | `AudioPlaybackPayload` | Base64 audio for browser playback |
| `terminal_output` | `TerminalOutputPayload` | Bash command running/streaming/completed |
| `generation_preview` | `GenerationPreviewPayload` | Image/video generation progress |
| `context_usage` | `ContextUsagePayload` | Context window fill ratio after each LLM call |
| `desktop_active` | `DesktopActivePayload` | Desktop environment started |
| `agent_started` | `AgentStartedPayload` | Sub-agent began execution |
| `agent_completed` | `AgentCompletedPayload` | Sub-agent finished (success/error/stopped) |
| `spawn_requested` | `SpawnRequestedPayload` | spawn_agent tool about to spawn a sub-agent |

**Serialization:** `event.model_dump(mode="json", exclude_none=True, exclude_defaults=True)` sent as JSONL line

## Related Entities

- [[EventDispatcher]] (distributes events)
- [[turn_scope]] (lifecycle, triggers `TurnEndPayload` on exit)
- [[ContentPayload]] (main content streaming type)
- [[ContextUsagePayload]] (published by [[ContextManager]])
- [[TerminalOutputPayload]] (published by [[run_bash_cmd]])
- [[BrowserScreenshotPayload]] (published by browser tools)

## Sources

- [[Source - SDK Overview]]
