---
title: API Routes
type: entity
tags: [server, http, api, routes]
created: 2026-07-07
updated: 2026-07-07
verified_commit: 6a5625d
paths:
  - "server/aiohttp_app.py"
  - "server/_conversation_routes.py"
  - "server/_profile_routes.py"
  - "server/_provider_routes.py"
  - "server/_settings_routes.py"
  - "server/_integrations_routes.py"
  - "server/_model_routes.py"
  - "server/_skill_routes.py"
  - "server/_task_routes.py"
  - "server/_feature_routes.py"
---

# API Routes

## Overview

The aiohttp server (`server/aiohttp_app.py:create_app()`) registers all HTTP routes. Routes are split across multiple modules; `create_app()` calls each module's `register_*_routes(app)` function to mount them.

## Route Summary

### Chat (in `aiohttp_app.py`)

| Method | Path | Handler | Purpose |
|--------|------|---------|---------|
| POST | `/api/chat` | `chat_handler` | Send message; returns JSONL SSE stream |
| POST | `/api/chat/stop` | `stop_handler` | Interrupt active turn |
| POST | `/api/nudge` | `nudge_handler` | Inject mid-turn user message |

### Memory

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/memory` | List all stored memories |
| DELETE | `/api/memory/{key}` | Delete a memory entry |
| POST | `/api/memory/{key}/hidden` | Toggle hidden flag |

### Custom Tools

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/custom-tools` | List all custom tools |
| DELETE | `/api/custom-tools/{name}` | Delete a custom tool |

### Conversations (`_conversation_routes.py`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/conversations` | List conversations |
| GET | `/api/conversations/{id}/resume` | Load conversation history + events for resume |
| DELETE | `/api/conversations/{id}` | Delete a conversation |
| PATCH | `/api/conversations/{id}` | Update conversation metadata (title, etc.) |

### Agent Profiles (`_profile_routes.py`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/profiles` | List profiles |
| POST | `/api/profiles` | Create profile |
| PUT | `/api/profiles/{id}` | Update profile |
| DELETE | `/api/profiles/{id}` | Delete profile |
| POST | `/api/profiles/{id}/duplicate` | Duplicate profile |

### Providers (`_provider_routes.py`)

Manage LLM provider configurations (API keys, base URLs).

### Models (`_model_routes.py`)

List available models from configured providers.

### Settings (`_settings_routes.py`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/settings` | Get app settings |
| PUT | `/api/settings` | Update app settings |

### Tasks (`_task_routes.py`)

CRUD for goals/routines and their run history.

### Integrations (`_integrations_routes.py`, `_integrations_oauth_routes.py`)

CRUD for integrations; OAuth callback handling.

### Skills (`_skill_routes.py`)

Read/write user-editable skills.

### Tool Categories (`_tool_category_routes.py`)

Catalog of tool categories for the UI.

### Features (`_feature_routes.py`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/features` | Return enabled feature flags |

### Static / UI

| Path | Purpose |
|------|---------|
| `/` | `index.html` (React SPA entry) |
| `/assets/*` | Vite-built JS/CSS bundles |
| `/static/*` | Static files (browser test pages, logos) |
| `{home_dir}/{path}` | Serve files from the agent's virtual computer |

## Middleware

A single `cors_and_error_middleware` wraps all requests:
- **CORS:** adds `Access-Control-Allow-*` headers to every response; handles OPTIONS preflight
- **CSRF:** mutating methods (POST/PUT/DELETE) require `X-Requested-With: XMLHttpRequest`; cross-origin JS cannot set this header (not listed in `Access-Control-Allow-Headers`)
- **Validation errors:** converts Pydantic `ValidationError` to `{"error": "Invalid request"}` with 400

## Related Entities

- [[Turn Lifecycle]] — chat routes drive turns
- [[Integrations Architecture]] — integrations routes

## Sources

- `server/aiohttp_app.py`
