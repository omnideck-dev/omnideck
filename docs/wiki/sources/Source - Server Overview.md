---
title: "Source - Server Overview"
type: source
tags: [server, aiohttp, api, routes, ui, react, streaming]
created: 2026-06-22
updated: 2026-06-22
sources: []
---

# Source - Server Overview

## Summary

The `server/` package implements the aiohttp-based HTTP API and serves the React frontend. The app factory (`create_app()` in `aiohttp_app.py`) registers all routes, sets up startup/cleanup hooks, and implements a staged readiness system. The `message_handler.py` module is the bridge between HTTP requests and the agent loop — it manages conversation cache (LRU), builds agents from profiles, drives the turn, and streams events back to the client as JSONL.

## Key Points

**App factory (`server/aiohttp_app.py`):**
- `create_app()` returns a configured `aiohttp.web.Application`
- CORS middleware + lightweight CSRF guard (X-Requested-With header check)
- Staged startup: data migrations → readiness signals → deferred subsystems
- Two readiness contributors: `setup_ready` (setup wizard complete) and `integrations_ready` (supervisor cache loaded)
- Deferred subsystems wait for all readiness signals before initializing; currently: `TaskRunner`
- Integrations cache load has a 30s deadline with 1s retry; if unreachable, deferred subsystems start anyway

**Core API routes:**
- `POST /api/chat` — streams JSONL `AgentEvent` responses
- `POST /api/chat/stop` — stops an active turn by conversation ID
- `POST /api/nudge` — sends a nudge message to a running agent
- `GET /api/memory`, `DELETE /api/memory/{key}`, `POST /api/memory/{key}/hidden`
- `GET /api/custom-tools`, `DELETE /api/custom-tools/{name}`
- `POST /api/desktop/start`
- Container file serving: `GET /{home_dir}/{path:.*}` — serves files from virtual computer home directory

**Registered route groups:**
- `_browser_control_routes` — WebSocket for browser takeover
- `_conversation_routes` — conversation session management
- `_feature_routes` — feature flag exposure
- `_integrations_routes` + `_integrations_oauth_routes` — integrations API
- `_model_routes`, `_provider_routes` — model/provider listing
- `_profile_routes` — agent profile CRUD
- `_skill_routes` — skill management
- `_tool_category_routes` — tool catalog
- `_settings_routes` — read/write settings.json
- `_setup_routes` — setup wizard completion

**Message handler (`server/message_handler.py`):**
- LRU conversation cache of 25 entries (backed by `ConversationHistory` in memory)
- Conversation eviction skips active turns to prevent write conflicts
- Per-turn: builds `AgentState` from profile, creates `ContextManager`, enters `turn_scope`, runs `run_turn`
- Events published inside the turn are queued via async queue and yielded to the streaming response
- After-turn: persists loaded skills, saves agent events, generates conversation title (background task)
- `_refresh_system_message` re-inserts memory into system prompt before each model call

**React UI:**
- Built with Vite, served from `server/ui/dist/`
- Static assets at `/assets/`, static files at `/static/`
- `GET /` serves `ui/dist/index.html`

## Entities Mentioned

- [[MessageHandler]]
- [[ConversationHistory]]
- [[AgentProfile]]
- [[AgentState]]
- [[ContextManager]]
- [[TaskRunner]]
- [[EventDispatcher]]
- [[AgentEvent]]
- [[turn_scope]]

## Concepts Covered

- [[Turn Lifecycle]]
- [[Agent Loop]]
- [[Conversation and Memory Persistence]]
- [[Multi-Agent Architecture]]

## Raw Notes

- CSRF guard: mutating requests (POST/PUT/DELETE) must carry `X-Requested-With: XMLHttpRequest`; this header is not in `Access-Control-Allow-Headers` so cross-origin JS can't set it
- Conversation title generated asynchronously after first turn — non-blocking
- `_MAX_CACHED_CONVERSATIONS = 25` — LRU eviction with active-turn protection
- File serving uses `is_relative_to` path guard to prevent path traversal
- `client_max_size=10 * 1024**2` (10 MB) upload limit for attachments
