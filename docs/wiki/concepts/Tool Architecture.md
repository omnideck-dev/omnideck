---
title: Tool Architecture
type: concept
tags: [tools, agent, llm, virtual-computer, browser, skills]
created: 2026-07-07
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "tools/"
  - "skills/"
  - "agent_core/tools/"
---

# Tool Architecture

## Overview

Tools are Python callables the LLM can invoke during a turn. Every tool is a plain
`async def` function with a Google-style docstring — the docstring *is* the schema the
model sees. `agent_core/tools/_callable_schema.py:callable_to_json_schema()` converts
a callable's signature and docstring into an OpenAI-style JSON schema at call time, for
providers that need explicit schemas (OpenAI, Anthropic); Ollama accepts raw callables.

Formerly this lived at `sdk/tools/`; `sdk/` is now a dead, unimported package — the
tool-calling machinery moved to `agent_core/tools/`, and the schema generator is
`agent_core/tools/_callable_schema.py` (previously documented as a bare
`callable_to_json_schema` entity page, now folded into this page).

Which tools an agent actually has access to is **not** a global registry — it's
resolved per profile through the [[Skill System]]: a profile loads a set of skills, each
skill grants one or more **tool categories**, and `skills/_tool_categories.py:tool_categories()`
expands those categories into live callables. See [[Skill System]] for the full
category → skill → profile chain.

## Tool Categories

| Category | Package | Notes |
|----------|---------|-------|
| `coding` | `tools/virtual_computer/` | File + bash sandbox — see [[Sandboxed Code Execution]] |
| `browser` | `tools/browser/` | Playwright web automation — see [[Browser Automation]] |
| `webfetch` | `tools/web/` | `fetch_url` — fetch a page as clean text, no browser |
| `memory` | `tools/memory/` | Persistent key-value store, `remember`/`forget`/`load_memory` |
| `planning` | `tasks/` | `begin_routine`, `add_task`, `commit_routine`, etc. — see [[Task Engine]] |
| `custom_tools` | `tools/custom_tools/` | Settings-gated; see below |
| `image_generation` / `music_generation` | `tools/generation/` | Feature-flag gated (`ENABLE_IMAGE_GEN` / `ENABLE_MUSIC_GEN`) |
| `desktop` | `tools/desktop/` | Feature-flag gated (`ENABLE_DESKTOP`); Xfce4/X11 GUI control |
| `email` / `calendar` / `drive` / `contacts` / `http` | `tools/integrations/` | Integration-backed; tools only appear once the integration is connected — see [[Integrations Architecture]] |

`skills/_tool_categories.py` builds the static, feature-gated categories once (cached)
and resolves the integration-backed categories per call against a live connection
snapshot — a category with nothing connected simply contributes an empty tool list
rather than erroring.

### Custom Tools (`tools/custom_tools/`)

User-defined tools, created at runtime by the agent itself via `create_custom_tool`.
Definitions persist as JSON in `registry.json` (`tools/custom_tools/registry.py`);
`command`-type tools run a shell template with `{param}` substitution, `program`-type
tools write a saved Python/bash script into `custom_tools/scripts/` under the virtual
computer's home directory and pipe JSON args to it on stdin
(`tools/custom_tools/executor.py:execute_custom_tool()`). Dependencies are installed
with `sudo pip3 install` / `npm install -g` once per process, cached in memory. Runs as
the `computron` user inside the container — no sandboxing beyond the container boundary
itself (same as a shell tool call).

### Scratchpad (`tools/scratchpad/`)

Disk-backed key-value notes per conversation, at
`<home_dir>/conversations/{conv_id}/scratchpad.json`, with an in-memory `ContextVar`
cache. `save_to_scratchpad` / `recall_from_scratchpad` — meant for an agent to park
intermediate findings (e.g. "which card was at which position") that would otherwise
fall out of context.

### Misc (`tools/misc/`)

`get_datetime` — current time/timezone, in `tools/misc/datetime.py`.

## Where It Lives

| Path | Role |
|------|------|
| `agent_core/tools/_callable_schema.py` | `callable_to_json_schema()`, `estimate_tool_tokens()` |
| `agent_core/tools/_helpers.py` | Tool-call execution/argument/result plumbing |
| `skills/_tool_categories.py` | `tool_categories()` — builds the category → tools map |
| `tools/browser/` | Playwright web automation (LLM-facing wrapper; see [[Browser Automation]]) |
| `tools/virtual_computer/` | File + bash sandbox (see [[Sandboxed Code Execution]]) |
| `tools/memory/memory.py` | Persistent memory store |
| `tools/integrations/` | Integration verb wrappers (thin bridge to `integrations.service`) |
| `tools/custom_tools/` | User-defined tool registry and executor |
| `tools/generation/` | Image/music generation |
| `tools/desktop/` | X11 desktop automation |
| `tools/scratchpad/` | Per-conversation scratchpad |
| `tools/misc/` | `get_datetime` |

## Key Details

- **Docstrings are the schema.** `callable_to_json_schema()` parses the Google-style
  `Args:` section with a regex to build per-parameter descriptions — a malformed
  docstring silently degrades to a schema with no parameter descriptions, not an error.
- **`eval_str=True`** on `inspect.signature()` is required to resolve string
  annotations from `from __future__ import annotations` modules — without it, every
  such tool's parameters collapse to the default `string` type.
- **Event emission:** tools call `publish_event(AgentEvent(...))` (from
  `agent_core.events`) directly to surface activity in the UI — see [[Event System]].
- **Tool categories, not individual tools, are the unit a skill grants** — see
  [[Skill System]] for why (keeps skill records stable as tools inside a category
  change).
- **Integration categories carry a `connected` flag** so the UI can show a skill as
  available-but-not-connected rather than simply omitting it.

## Open Questions

- Custom tools run as arbitrary Python/bash in the container as the `computron` user —
  confirm whether any additional seccomp/namespace sandboxing wraps this beyond the
  container boundary (not found in `tools/custom_tools/`).

## Sources

- `docs/integrations.md` — integration tool security model
