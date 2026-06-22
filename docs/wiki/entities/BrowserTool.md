---
title: BrowserTool
type: entity
tags: [browser, playwright, automation, tools]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - Tools Overview]]"]
---

# BrowserTool

## Overview

The browser tools (in `tools/browser/`) provide Playwright-based web automation. A single long-lived browser instance is shared across all tool calls in a process, maintaining session state (cookies, localStorage, tabs) between calls. The tools expose both structural (accessibility snapshot) and visual (screenshot + vision model) interaction modes.

## Details

**Browser lifecycle:**
- `get_browser()` — lazily initializes the Playwright browser instance
- `close_browser()` — cleanly closes it (called on app shutdown)
- `release_agent_browser(agent_id)` — closes pages belonging to a specific agent/conversation

**Navigation tools:**
- `goto(url, tab_id=None)` — navigate (creates first tab if none exist)
- `new_tab(url)` → new tab ID
- `close_tab(tab_id)`

**Reading tools:**
- `browse_page(scope=None)` — returns accessibility snapshot with `[role] name` markers for interactive elements
- `read_page()` — returns clean markdown text (best for articles/docs)
- `inspect_page(question)` — uses vision model to answer a question about the page
- `browser_visual_action(instruction)` — vision model decides and executes the next GUI action

**Interaction tools (return formatted page view string):**
- `click(ref)`, `fill_field(ref, value)`, `press_keys(keys)`, `select_option(ref, value)`
- `scroll_page(direction, amount)`, `go_back()`, `drag(source, target)`
- `press_and_hold(key)`, `execute_javascript(code)`

**Screenshot events:** after navigation/interaction, tools publish `BrowserScreenshotPayload` events with base64 PNG, tab ID, and open tab set; UI uses these to maintain per-tab thumbnail previews

**Human-like interactions:** configurable delays for typing (40-120ms per char, extra pauses every 6 chars) and pointer movements (80-160ms hover, 25-60ms click hold)

**Guard rails:**
- `scroll_warn_threshold=5` — warns after N scrolls in same direction
- `scroll_hard_limit=10` — hard stop to prevent infinite scroll loops
- `max_open_tabs=5` — refuses to open more tabs

**Vision integration:** `inspect_page` and `browser_visual_action` call the configured vision provider/model from `settings.vision_provider/vision_model`

## Related Entities

- [[VirtualComputerTool]] (complementary tool set)
- [[BrowserScreenshotPayload]] (emitted by browser tools)
- [[AgentState]] (tools registered here)
- [[Settings]] (vision provider config)

## Sources

- [[Source - Tools Overview]]
