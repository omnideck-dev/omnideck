---
title: "Source - Tools Overview"
type: source
tags: [tools, browser, virtual-computer, memory, web, generation, integrations]
created: 2026-06-22
updated: 2026-06-22
sources: []
---

# Source - Tools Overview

## Summary

The `tools/` package contains all LLM-callable tool implementations. Major sub-packages include `browser/` (Playwright-based web automation), `virtual_computer/` (file system, bash execution, package installation), `memory/` (key-value persistent memory), `web/` (HTTP fetch), `generation/` (image/music/video generation), `integrations/` (Gmail, Calendar, Drive via broker client), and `desktop/` (Xfce desktop agent). Tool functions use Google-style docstrings which `callable_to_json_schema` converts to JSON Schema for LLM consumption.

## Key Points

**Browser tools (`tools/browser/`):**
- Long-lived Playwright browser instance shared across tool calls (cookies, localStorage persist between calls)
- Tools: `goto`, `new_tab`, `close_tab`, `browse_page`, `read_page`, `click`, `fill_field`, `press_keys`, `select_option`, `scroll_page`, `go_back`, `drag`, `execute_javascript`, `inspect_page`, `browser_visual_action`, `save_page_content`
- `browse_page` returns `[role] name` markers for interactive elements (aria snapshot)
- `read_page` returns clean markdown for reading text content
- `inspect_page` and `browser_visual_action` use vision model for GUI understanding
- `close_browser` / `release_agent_browser` for cleanup

**Virtual computer tools (`tools/virtual_computer/`):**
- File ops: `write_file`, `read_file`, `list_dir`, `make_dirs`, `remove_path`, `copy_path`, `move_path`, `append_to_file`, `prepend_to_file`, `head`, `tail`
- Edit ops: `insert_text`, `replace_in_file`, `apply_text_patch`, `apply_unified_diff`
- Search: `grep`
- Execution: `run_bash_cmd` — runs under `set -euo pipefail`, 120s default timeout, streams stdout/stderr via events, kills entire process group on timeout
- Package install: `install_packages` (auto-promotes to root)
- Other: `send_file` (emits `FileOutputPayload`), `play_audio`, `describe_image`, `receive_attachment`
- Execution policy via `_policy.py` — deny patterns checked before running commands

**Memory tools (`tools/memory/`):**
- `remember(key, value)` — stores in `memory.json` with atomic write
- `forget(key)` — removes by key
- Hidden key support for privacy (UI hides marked keys)

**Web tools (`tools/web/`):**
- `fetch_url` — HTTP GET/POST with response body

**Tool schema generation (`sdk/tools/_callable_schema.py`):**
- `callable_to_json_schema(func)` — converts Python callable to OpenAI-style tool JSON schema
- Reads Google-style docstrings for parameter descriptions
- Handles `Optional`, `Union`, `list[T]`, `dict` type annotations

## Entities Mentioned

- [[BrowserTool]]
- [[VirtualComputerTool]]
- [[MemoryTool]]
- [[WebFetchTool]]
- [[run_bash_cmd]]
- [[callable_to_json_schema]]
- [[BrowserScreenshotPayload]]
- [[TerminalOutputPayload]]
- [[FileOutputPayload]]

## Concepts Covered

- [[Browser Automation]]
- [[Sandboxed Code Execution]]
- [[Tool Schema Generation and Dispatch]]
- [[Conversation and Memory Persistence]]

## Raw Notes

- Browser is process-global, not per-conversation — a tab opened in one conversation persists until explicitly closed
- `release_agent_browser(agent_id)` closes browser pages associated with a particular agent/conversation scope
- `scroll_warn_threshold=5` and `scroll_hard_limit=10` prevent infinite scroll loops
- `max_open_tabs=5` cap prevents tab explosion
- Human-like browser interactions: configurable typing delays, pointer hover/click timing
- `run_bash_cmd` emits `TerminalOutputPayload` with status "running", "streaming", "completed"
