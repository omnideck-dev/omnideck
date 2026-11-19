---
title: API Routes
type: entity
tags: [server, http, api, routes]
created: 2026-07-07
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "server/aiohttp_app.py"
  - "server/_agent_run_routes.py"
  - "server/_artifacts_routes.py"
  - "server/_browser_control_routes.py"
  - "server/_browser_profile_routes.py"
  - "server/_container_file_routes.py"
  - "server/_conversation_routes.py"
  - "server/_custom_app_routes.py"
  - "server/_custom_tool_routes.py"
  - "server/_desktop_routes.py"
  - "server/_feature_routes.py"
  - "server/_integrations_oauth_routes.py"
  - "server/_integrations_routes.py"
  - "server/_memory_routes.py"
  - "server/_model_routes.py"
  - "server/_pack_routes.py"
  - "server/_profile_routes.py"
  - "server/_provider_routes.py"
  - "server/_settings_routes.py"
  - "server/_setup_routes.py"
  - "server/_skill_routes.py"
  - "server/_task_routes.py"
  - "server/_tool_category_routes.py"
  - "server/_ui_routes.py"
---

# API Routes

## Overview

The aiohttp server (`server/aiohttp_app.py:create_app()`) registers all HTTP routes. Routes are split across one module per feature domain (`server/_*_routes.py`); each exports a `register_*_routes(app)` function that `create_app()` calls. There are now 23 such modules — the route surface has grown substantially since this page was last verified (previously 10 modules at commit `6a5625d`).

**Formerly `server/message_handler.py` doesn't exist anymore.** Chat HTTP handling moved into `server/_agent_run_routes.py`, which adapts the legacy chat-shaped wire contract onto the newer, channel-neutral `agent_runtime.AgentRuntime` abstraction (see below and [[Turn Lifecycle]]).

## Route Summary

### Agent Runs (`_agent_run_routes.py`)

The legacy `/api/chat` URLs stay stable for the browser, but underneath they now go through `agent_runtime.AgentRuntime` — a channel-neutral run abstraction with resumable, cursor-addressed event replay (`run_id` + `seq`), not a single direct pass-through SSE stream. `ChatRequest`/`NudgeRequest` Pydantic models translate the chat wire shape into an `AgentRunRequest`.

| Method | Path | Handler | Purpose |
|--------|------|---------|---------|
| POST | `/api/chat` | `chat_handler` | Start a run and stream its events as JSONL |
| GET | `/api/chat/runs/{run_id}/events` | `chat_run_events_handler` | Replay-then-follow an active or recent run by ID |
| POST | `/api/chat/stop` | `stop_handler` | Request cooperative stop of a run |
| POST | `/api/nudge` | `nudge_handler` | Inject a message into the active root-agent turn |

`stream_events()` writes each `SequencedEvent` as one JSON line (`Transfer-Encoding: chunked`), with `run_id` and `seq` merged into the payload for client-side cursor tracking.

### Artifacts (`_artifacts_routes.py`)

New since the last wiki pass — no page previously existed. Likely backed by the top-level `artifacts/` package.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/artifacts` | List artifacts |
| POST | `/api/artifacts/prune-missing` | Remove index entries whose backing files are gone |
| GET | `/api/artifacts/{artifact_id}` | Get one artifact |
| DELETE | `/api/artifacts/{artifact_id}` | Delete an artifact |

### Browser Control & Profiles (`_browser_control_routes.py`, `_browser_profile_routes.py`)

New since the last wiki pass. Lets a human take over the shared browser session and manages saved browser profiles/state.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/browser/control` | WebSocket side-channel for human browser takeover |
| GET | `/api/browser/session` | Current browser session info |
| POST | `/api/browser/session/load` | Load a saved session |
| POST | `/api/browser/session/save` | Save current session |
| GET | `/api/browser/session/preview` | Preview a saved session |
| GET | `/api/browser/profiles` | List browser profiles |
| PUT / DELETE | `/api/browser/profiles/{id}` | Update / delete a profile |
| DELETE | `/api/browser/profiles/{id}/sites` | Clear a profile's remembered sites |
| DELETE | `/api/browser/profiles/{id}/state` | Clear a profile's persisted browser state |
| POST | `/api/browser/conversations/{conversation_id}/save` | Save a takeover session against a conversation |
| GET | `/api/browser/conversations/{conversation_id}/preview` | Preview a conversation's saved takeover |

### Container Files (`_container_file_routes.py`)

New since the last wiki pass. Lets the frontend (and agent-authored HTML) reference virtual-computer files by real path instead of base64-encoding them.

| Method | Path | Purpose |
|--------|------|---------|
| GET / HEAD | `{home_prefix}/{path:.*}` | Read a file (HEAD for Last-Modified/ETag polling without the body) |
| PUT | `{home_prefix}/{path:.*}` | Write a file (e.g. from a source editor) |

Registered twice — once under the configured `virtual_computer.home_dir` prefix, once under the hardcoded legacy `/home/computron` alias, so old stored content referencing the previous path keeps resolving.

### Conversations (`_conversation_routes.py`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/conversations/sessions` | List conversations |
| GET | `/api/conversations/archived` | List archived conversations |
| GET / POST | `/api/conversations/folders` | List / create folders |
| PATCH / DELETE | `/api/conversations/folders/{folder_id}` | Update / delete a folder |
| POST | `/api/conversations/sessions/{id}/resume` | Load history + events for resume |
| POST | `/api/conversations/sessions/{id}/title` | Generate a title |
| POST | `/api/conversations/sessions/{id}/archive` | Archive |
| POST | `/api/conversations/sessions/{id}/unarchive` | Unarchive |
| PUT | `/api/conversations/sessions/{id}/preview-state` | Save which files/tabs are open in the preview panel |
| PATCH / DELETE | `/api/conversations/sessions/{id}` | Update metadata / delete |

The collection route (`/sessions`) is registered before the per-ID wildcard so aiohttp's matcher doesn't treat `sessions` as an `{id}`.

### Custom Apps & Custom Tools (`_custom_app_routes.py`, `_custom_tool_routes.py`)

Custom Apps are new since the last wiki pass ("Experimental" per the registration comment in `create_app()`) — agent- or user-authored mini web apps served under their own path, with an SDK script and an invoke action endpoint. Custom Tools (previously documented) remain unchanged in shape.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/custom-apps` | List custom apps |
| PUT / DELETE | `/api/custom-apps/home` | Set / clear the "home" custom app |
| GET | `/api/custom-apps/sdk.js` | JS SDK for custom apps to call back into Omnideck |
| GET | `/api/custom-apps/{slug}/web/{path:.*}` | Serve a custom app's static files |
| POST | `/api/custom-apps/{slug}/invoke/{action}` | Invoke a custom app action |
| GET | `/api/custom-tools` | List custom tools |
| DELETE | `/api/custom-tools/{name}` | Delete a custom tool |

### Desktop (`_desktop_routes.py`)

New since the last wiki pass.

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/desktop/start` | Start the shared desktop environment (Xfce/VNC); 503 on `DesktopExecError` |

### Features (`_feature_routes.py`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/features` | Return enabled feature flags |

### Integrations (`_integrations_routes.py`, `_integrations_oauth_routes.py`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/integrations` | List configured integrations |
| GET | `/api/integrations/catalog` | List available integration types |
| POST | `/api/integrations` | Add an integration |
| PATCH | `/api/integrations/{id}` | Update an integration |
| POST | `/api/integrations/{id}/reconnect` | Reconnect |
| DELETE | `/api/integrations/{id}` | Remove |
| POST | `/api/integrations/oauth/start` | Start an OAuth flow |
| GET | `/api/integrations/oauth/callback` | OAuth provider callback |
| GET / DELETE | `/api/integrations/oauth/status/{state}` | Poll / cancel an in-flight OAuth flow |

See [[Integrations Architecture]] for what's underneath these (owned by another wiki cluster — not independently re-verified here).

### Memory (`_memory_routes.py`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/memory` | List stored memories |
| DELETE | `/api/memory/{key}` | Delete a memory entry |
| POST | `/api/memory/{key}/hidden` | Toggle hidden flag |

### Models & Providers (`_model_routes.py`, `_provider_routes.py`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/models` | List available models from configured providers |
| POST | `/api/models/refresh` | Refresh the model list |
| GET | `/api/providers` | List provider configs |
| POST | `/api/providers` | Add a provider |
| PATCH / DELETE | `/api/providers/{name}` | Update / remove a provider |

### Packs (`_pack_routes.py`)

New since the last wiki pass — export/import for sharing profiles and skills as portable "packs".

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/pack/export/profiles/{id}` | Export a profile as a pack |
| GET | `/api/pack/export/skills/{id}` | Export a skill as a pack |
| POST | `/api/pack/import` | Import a pack |

### Agent Profiles (`_profile_routes.py`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/agents` | List agents (alias over profiles) |
| GET / POST | `/api/profiles` | List / create profiles |
| GET / PUT / DELETE | `/api/profiles/{id}` | Get / update / delete a profile |
| POST | `/api/profiles/{id}/duplicate` | Duplicate |
| GET | `/api/profiles/{id}/usage` | Usage info for a profile (new — not in the previous wiki pass) |

### Settings & Setup (`_settings_routes.py`, `_setup_routes.py`)

| Method | Path | Purpose |
|--------|------|---------|
| GET / PUT | `/api/settings` | Get / update app settings |
| GET | `/api/setup/defaults` | Defaults for the first-run wizard |
| POST | `/api/setup/complete` | Mark setup complete |

### Skills (`_skill_routes.py`)

| Method | Path | Purpose |
|--------|------|---------|
| GET / POST | `/api/skills` | List / create skills |
| GET / PUT / DELETE | `/api/skills/{id}` | Get / update / delete a skill |

### Routines (`_task_routes.py`)

**Renamed from "Tasks"/"Goals" in the previous wiki pass — the UI and API both now say "Routines".** The underlying service object is still `RoutineService`/`TaskRunner`/`TaskExecutor` (see [[Task Engine]]).

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/routines` | List routines |
| GET / DELETE | `/api/routines/{id}` | Get / delete a routine |
| POST | `/api/routines/{id}/pause` \| `/resume` \| `/trigger` | Control a routine |
| GET | `/api/routines/{id}/runs` | List a routine's run history |
| DELETE | `/api/routines/{id}/runs/{run_id}` | Delete a run record |
| GET | `/api/runner/status` | Runner status |
| POST | `/api/runner/pause` \| `/api/runner/resume` | Pause / resume the whole runner |

### Tool Categories (`_tool_category_routes.py`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/tool-categories` | Catalog of tool categories for the UI |

### Static / UI (`_ui_routes.py`)

| Path | Purpose |
|------|---------|
| `/` | `index.html` (React SPA entry) |
| `/custom.css` | User custom CSS override |
| `/manifest.webmanifest` | PWA manifest |
| `/assets/*` | Vite-built JS/CSS bundles (static route, not in `_ui_routes.py`) |

## Middleware

A single `cors_and_error_middleware` wraps all requests (unchanged in shape from the previous pass):

- **CORS:** adds `Access-Control-Allow-*` headers to every response; handles OPTIONS preflight.
- **CSRF:** mutating methods POST/PUT/DELETE require `X-Requested-With: XMLHttpRequest`; cross-origin JS cannot set this header (it's deliberately not listed in `Access-Control-Allow-Headers`), so its presence signals a same-origin request. **PATCH is not in the CSRF-checked method set** — see [[Adding a New API Route]] for the implication.
- **Validation errors:** converts Pydantic `ValidationError` to `{"error": "Invalid request"}` with 400.

## App-Level State

`create_app()` now constructs and stores several long-lived objects on the `web.Application` at startup, keyed by module-level `*_KEY` constants: a `BrowserRuntime`, an `IntegrationConnectionCache`, and an `AgentRuntime` (from `agent_runtime`, composed from a `ConversationStore`, the browser runtime, and the integration cache). Route handlers read these back out of `request.app[...]` rather than constructing their own. See [[App Startup]].

## Related Entities

- [[Turn Lifecycle]] — what `agent_runtime.AgentRuntime` drives per chat request
- [[App Startup]] — where all `register_*_routes` calls happen and what else boots alongside them
- [[Task Engine]] — behind the Routines routes

## Open Questions

- Whether the run-cursor/replay model behind `/api/chat/runs/{run_id}/events` has (or should have) its own concept page, or stays folded into [[Turn Lifecycle]] — not resolved here since `agent_runtime` internals belong to another part of this regeneration.

## Sources

- `server/aiohttp_app.py`
- `server/_agent_run_routes.py`
