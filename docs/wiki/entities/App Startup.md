---
title: App Startup
type: entity
tags: [server, startup, aiohttp, readiness]
created: 2026-07-07
updated: 2026-07-07
verified_commit: 6a5625d
paths:
  - "main.py"
  - "server/aiohttp_app.py"
---

# App Startup

## Overview

The app boots in three sequential phases managed by aiohttp's `on_startup` hook list. This structure ensures data migrations complete before any request is served, and that subsystems gated on external readiness (setup wizard completion, integrations cache) don't block the HTTP server from accepting connections.

## Location

`main.py` (entry point), `server/aiohttp_app.py:create_app()` (all startup logic).

## Phases

### Phase 1: Data Migrations

`_run_data_migrations(app)` runs synchronous migration scripts in `migrations/` against the state directory. This completes before any route handler runs.

### Phase 2: Readiness Signals

Two contributors register events that must all fire before deferred subsystems start:

- **Setup readiness** (`_init_setup_signal`): fires immediately if the setup wizard was already completed; waits if not.
- **Integrations readiness** (`_init_integrations_signal`): attempts to load the integrations cache (supervisor socket) with a 30-second deadline and exponential retry. Fires even on timeout so the app doesn't hang forever — chat works without integrations.

`_init_ready_signal` aggregates both contributors into `app["ready"]`.

### Phase 3: Deferred Subsystems

`_start_deferred_subsystems` spawns a background task that awaits `app["ready"]`, then starts:
- `TaskRunner` (goals/routines engine) — only if `GoalsConfig.enabled` is true

### Shutdown

`on_cleanup` hooks:
- `close_browser()` — tear down any open Playwright browser
- `_shutdown_executor()` — gracefully drain thread pool executors with a 5-second timeout; force-exits if they hang (avoids multi-Ctrl+C)

## Readiness Pattern

The pattern allows adding new gating signals without touching the deferred subsystem code:
1. Write `_init_my_signal(app)` startup hook that calls `register_ready_contributor(app, "my_name")` and signals the returned event when ready.
2. Register the hook in `create_app()` before `_init_ready_signal`.

## Related Entities

- [[AppConfig]] — loaded by `_run_data_migrations` and `_init_task_runner`
- [[Task Engine]] — started in Phase 3
- [[Integrations Architecture]] — integrations readiness contributor
- [[API Routes]] — all routes registered in `create_app()`

## Sources

- `server/aiohttp_app.py`
