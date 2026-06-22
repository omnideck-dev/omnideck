---
title: Browser Automation
type: concept
tags: [browser, playwright, automation, vision, screenshots]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - Tools Overview]]"]
---

# Browser Automation

## Overview

Browser automation in Omnideck is powered by Playwright (lazily imported). A single long-lived browser instance persists across tool calls within the app process, maintaining cookies, localStorage, and open tabs. The browser tools offer both structural (accessibility tree) and visual (screenshot + vision model) modes.

## How It Works

**Browser lifecycle:**
- Lazily initialized on first `goto()` call; runs headlessly or with a visible window (`config.tools.browser.headless`)
- Process-global: shared across all conversations (tabs are the isolation boundary)
- `close_browser()` called on app shutdown via `app.on_shutdown`
- `release_agent_browser(agent_id)` closes tabs associated with a specific conversation

**Two interaction modes:**

1. **Structural mode** (`browse_page`):
   - Returns an accessibility snapshot with `[role] name` markers for interactive elements
   - More reliable for structured UIs (forms, menus)
   - Uses Playwright's accessibility tree, not DOM scraping

2. **Visual mode** (`inspect_page`, `browser_visual_action`):
   - Takes a screenshot and sends to the configured vision model
   - `inspect_page(question)` → vision model answers a question about the page
   - `browser_visual_action(instruction)` → vision model decides the next action and executes it
   - Falls back to visual when accessibility tree is unreliable (e.g., canvas, custom widgets)

**Human-like interaction simulation:**
- Typing: 40-120ms delay per character, extra pause every 6 chars (150-300ms)
- Pointer: 80-160ms hover before click, 25-60ms click hold duration
- Configurable in `config.tools.browser.human`

**Screenshot events:**
- After navigation/interaction, tools publish `BrowserScreenshotPayload` with base64 PNG, current URL, tab ID, all open tab IDs
- UI uses this to maintain per-tab thumbnail previews
- Reconcile-only events (tab closed) carry `screenshot=None` but still update open_tab_ids

**Guard rails:**
- `max_open_tabs=5` — refuse to open more (prevents tab explosion)
- `scroll_warn_threshold=5`, `scroll_hard_limit=10` — prevent infinite scroll loops
- `network_idle_timeout_ms=3000`, `dom_mutation_timeout_ms=1500` — wait-for-load timeouts

## Key Details

- Playwright is lazily imported inside tool functions (heavy optional dep)
- `from __future__ import annotations` used in browser modules so import doesn't trigger Playwright load at module import time
- Browser state (cookies, auth sessions) persists until `close_browser()` — if an agent authenticates to a site, subsequent tool calls in the same process can use that session

## Sources

- [[Source - Tools Overview]]
