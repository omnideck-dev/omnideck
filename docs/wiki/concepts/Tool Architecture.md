---
title: Tool Architecture
type: concept
tags: [tools, agent, llm, virtual-computer, browser]
created: 2026-07-07
updated: 2026-07-07
verified_commit: 6a5625d
paths:
  - "tools/"
---

# Tool Architecture

## Overview

Tools are Python functions the LLM can invoke during a turn. They are passed to the `Agent` as a list of callables. All tool functions must have Google-style docstrings — these are the LLM's documentation for when and how to call each tool. The SDK wraps every call with `before_tool` / `after_tool` hook phases.

## Tool Categories

### Browser (`tools/browser/`)

Playwright-based web automation. Chrome runs headlessly inside the container. Key tools:

| Tool | File | Description |
|------|------|-------------|
| `navigate` | `navigation.py` | Go to a URL |
| `click` | `interactions.py` | Click an element with human-like pointer simulation |
| `type_text` | `interactions.py` | Type with simulated human timing |
| `scroll` | `interactions.py` | Scroll the page |
| `read_content` | `read_content.py` | Extract page text / structured content |
| `snapshot` | `snapshot_tool.py` | Accessibility tree snapshot for navigation |
| `browser_screenshot` | `vision.py` | Take a screenshot (emits `BrowserScreenshotPayload`) |
| `save_content` | `save_content.py` | Save page content to a file |

Browser state is per-agent: `release_agent_browser()` tears it down when a conversation is evicted from the LRU cache.

### Virtual Computer (`tools/virtual_computer/`)

File system and bash execution in the agent's home directory (`/home/computron`). The agent reads, writes, and runs code here.

| Tool | File | Description |
|------|------|-------------|
| `run_bash` | `run_bash_cmd.py` | Execute a shell command; emits `TerminalOutputPayload` |
| `read_file` | `read_ops.py` | Read file contents |
| `write_file` | `file_ops.py` | Write / overwrite a file |
| `edit_file` | `edit_ops.py` | Patch a file with string replacement |
| `list_files` | `stat_ops.py` | List directory contents |
| `search_files` | `search_ops.py` | Grep / find across files |
| `file_output` | `file_output.py` | Mark a file for UI download (emits `FileOutputPayload`) |
| `install_packages` | `install_packages.py` | `pip install` packages in the container |
| `receive_file` | `receive_file.py` | Write an uploaded attachment to disk |

A path policy (`_policy.py`) ensures all file operations stay within the agent's home directory.

### Memory (`tools/memory/`)

Persistent key-value store across conversations. Entries are stored as JSON and injected into the system prompt before each turn.

### Integrations (`tools/integrations/`)

Thin wrappers over `broker_client.call()` — see [[Integrations Architecture]].

### Custom Tools (`tools/custom_tools/`)

User-defined tools stored in the state directory. An LLM can create new tools via `create_custom_tool` (Python or bash snippets) and they become immediately available.

### Generation (`tools/generation/`)

Image and music generation using GPU models inside the container. Guarded by `ENABLE_IMAGE_GEN` / `ENABLE_MUSIC_GEN` feature flags. Emit `GenerationPreviewPayload` for real-time progress.

### Desktop (`tools/desktop/`)

Xfce4 desktop automation via X11 — for when the browser tool isn't sufficient. Guarded by `ENABLE_DESKTOP=1`.

### Misc (`tools/misc/`)

Simple utilities: `get_datetime` (current time/timezone).

### Scratchpad (`tools/scratchpad/`)

Internal agent scratch space — a text buffer the agent uses for planning and note-taking within a turn.

## Where It Lives

| Path | Role |
|------|------|
| `tools/__init__.py` | Re-exports and tool catalog |
| `tools/browser/` | Playwright web automation |
| `tools/virtual_computer/` | File + bash virtual computer |
| `tools/memory/` | Persistent memory store |
| `tools/integrations/` | Integration verb wrappers |
| `tools/custom_tools/` | User-defined tool registry and executor |
| `tools/generation/` | Image/music generation |
| `tools/desktop/` | X11 desktop automation |
| `tools/misc/` | Datetime and other simple tools |
| `tools/scratchpad/` | Per-turn scratchpad |

## Key Details

- **Docstrings are required** on every tool function — they become the LLM's schema for calling the tool.
- **Event emission:** tools call `publish_event(payload)` directly to surface their activity in the UI.
- **Tool resolution by profile skills:** `sdk/skills/build_agent_state()` assembles the tool list from the profile's `skills` list, not from a global registry. This means different profiles can expose different tool sets.
- **`_grounding.py`** bridges visual grounding (GPU model in the inference server) with browser interactions — used when `ENABLE_GROUNDING=1`.

## Open Questions

- Custom tools run as arbitrary Python/bash in the container as the `computron` user — no additional sandboxing beyond the container boundary.

## Sources

- `docs/integrations.md` — integration tool security model
