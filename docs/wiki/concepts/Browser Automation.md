---
title: Browser Automation
type: concept
tags: [browser, playwright, tools, agent]
created: 2026-10-18
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "browser/"
  - "tools/browser/"
---

# Browser Automation

## Overview

Omnideck gives the agent a real, Playwright-driven Chromium instance. The subsystem is
split across two packages:

- **`browser/`** (top-level) — the runtime domain: Chromium lifecycle, tab/document
  model, profile persistence, session pooling. No LLM concepts here at all.
- **`tools/browser/`** — the LLM-facing tool surface: thin `async def` functions with
  Google-style docstrings that resolve the current agent's browser and call into
  `browser/`.

This split means "browser automation" (can the agent use a web browser at all) and
"the browser tool" (what functions the model can call) are different layers — useful
when tracing a bug: a broken navigation is probably in `browser/core/`, a confusing
tool description is probably in `tools/browser/`.

## How It Works

### 1. Runtime: `Browser`, `Tab`, `Document`

`browser/core/browser.py:Browser` wraps a Playwright `BrowserContext`. It owns tabs,
exposes `navigate()`, `new_tab()`, `navigate_back()`, and returns an `ActionResult`
(tab, navigation response, download info, timing) for every action. `browser/core/tab.py`
and `browser/core/document.py` model a single tab and its current rendered page.
Challenge detection (`browser/core/challenges.py`) and download capture
(`browser/core/downloads.py`) live alongside.

### 2. Session lifecycle: `BrowserRuntime` and `BrowserSessionPool`

`browser/runtime.py:BrowserRuntime` is the coordinator between saved profiles and live
sessions. Key behavior:

- **Root vs. child scope.** A root agent's browser (`parent_execution_id is None`)
  lives for the whole conversation and is keyed by `conversation:{id}`; a sub-agent's
  browser is scoped to its own execution and torn down when that execution ends. This
  mirrors the agent-span nesting described in [[Turn Lifecycle]].
- **`get_browser()`** (module-level function) reads a `ContextVar` set by
  `BrowserRuntime.execution()` to return the `Browser` bound to whichever agent
  execution is currently running — this is how `tools/browser/*` resolves "the"
  browser without a parameter threading it through every call.
- **Profile resolution.** Each agent profile may reference a saved `BrowserProfile`
  (cookies/storage state) by id, or opt out entirely — `AgentBrowserBinding.
  browser_access_enabled` is `False` when `browser_profile_id is None`.
  An unavailable referenced profile falls back to the `EMPTY_BROWSER_PROFILE_ID`
  with a warning rather than failing the turn.
- **Separate user browser.** `ensure_user_browser()` / `load_user_browser_profile()`
  manage a *separate* browser session (keyed `"user"`) used by the UI's own
  browser-control surface, distinct from any agent's session.

`browser/session_pool.py:BrowserSessionPool` is the actual pool keyed by the strings
`BrowserRuntime` constructs (`conversation:{id}`, an `execution_id`, or `"user"`); it
lazily creates, replaces, and releases `Browser` instances and loads storage state via
a `BrowserStorageStateLoader` callback.

### 3. Profiles

`browser/profiles.py` (`BrowserProfile`, `BrowserProfileSite`) and
`browser/profile_store.py` (`BrowserProfileStore`, `DEFAULT_BROWSER_PROFILE_ID`,
`EMPTY_BROWSER_PROFILE_ID`) persist captured storage state (cookies, localStorage) so
a browser session can resume a logged-in site across conversations. `capture_storage_state()`
on `Browser` produces what gets saved.

### 4. The tool surface (`tools/browser/`)

Each tool is a plain async function; `tools/browser/_tool_context.py:get_tab()` /
`get_document()` resolve the current browser and a stable tab-id string (the model
refers to tabs by a short numeric-looking ID shown in every tool's output header, not
a Playwright handle). Representative tools:

| Tool | File | Notes |
|------|------|-------|
| `goto` | `navigation.py` | Navigate an *existing* tab — errors if two `goto` calls race on the same tab |
| `new_tab` | `navigation.py` | The only way to open a fresh tab |
| `close_tab` | `navigation.py` | ID is never reused after close |
| `browse_page` / `read_page` | `browse.py` / `read.py` | Structured `[role] name` view vs. clean markdown |
| `click`, `fill_field`, `press_keys`, `select_option`, `scroll_page`, `drag`, `press_and_hold` | `interactions.py` | Human-like interaction primitives |
| `go_back` | `navigation.py` | History navigation |
| `execute_javascript` | `scripting.py` | Escape hatch; docstring tells the model to prefer structured tools |
| `inspect_page`, `browser_visual_action` | `vision.py` | Vision-model-backed; `browser_visual_action` only registered when `visual_grounding` feature flag is on (see `skills/_tool_categories.py`) |
| `save_page_content` | `save.py` | Persist page content to a file |

Several tools use decorators from `tools/browser/events.py`
(`@emit_screenshot_after`, `emit_tab_state()`) to publish `AgentEvent`s so the UI shows
a live screenshot/tab list — see [[Event System]].

## Where It Lives

| Path | Role |
|------|------|
| `browser/core/browser.py` | `Browser`, `ActionResult` — the Playwright wrapper |
| `browser/core/tab.py`, `browser/core/document.py` | Tab and rendered-document model |
| `browser/runtime.py` | `BrowserRuntime`, `get_browser()`, root/child scoping |
| `browser/session_pool.py` | `BrowserSessionPool` — keyed session cache |
| `browser/profiles.py`, `browser/profile_store.py` | Saved storage-state profiles |
| `tools/browser/_tool_context.py` | `get_tab()`, `get_document()` — tool-boundary resolution |
| `tools/browser/navigation.py`, `interactions.py`, `browse.py`, `read.py`, `vision.py`, `scripting.py`, `save.py`, `select.py` | The individual LLM-facing tools |
| `tools/browser/events.py` | Screenshot/tab-state event emission decorators |

## Key Details

- **`browser` is a restricted tool category** — see [[Skill System]]; it can't be
  granted by a user-created skill, only by whatever an agent profile configures
  directly.
- **Root-agent browsers outlive a single turn**; sub-agent browsers don't. Getting
  this scope wrong (e.g. treating a sub-agent's browser as conversation-scoped) would
  leak sessions across unrelated executions.
- **Tab IDs are stable strings, not Playwright page handles** — every tool's output
  includes the current tab ID in its header so the model can reference it on the next
  call.

## Open Questions

- Visual grounding's `browser_visual_action` path (bridging to a GPU vision model) is
  described at the tool-registration level here; the grounding model/service details
  are out of this page's scope.

## Sources

- None beyond source code.
