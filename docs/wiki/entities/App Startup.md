---
title: App Startup
type: entity
tags: [server, startup, aiohttp, readiness]
created: 2026-07-07
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "main.py"
  - "server/aiohttp_app.py"
---

# App Startup

## Overview

The app boots in three sequential phases managed by aiohttp's `on_startup` hook list. This structure ensures data migrations complete before any request is served, and that subsystems gated on external readiness (setup wizard completion, integrations cache) don't block the HTTP server from accepting connections. Unchanged in shape since the last wiki pass; the details below are re-verified against current code.

## Location

`main.py` (entry point), `server/aiohttp_app.py:create_app()` (all startup logic).

## App Construction

Before any `on_startup` hook runs, `create_app()` builds and stores three long-lived objects directly on the `web.Application`:

- `BrowserRuntime` (from top-level `browser/`) → `BROWSER_RUNTIME_KEY`
- `IntegrationConnectionCache` wrapping `integrations.service.integration_service` → `INTEGRATION_CACHE_KEY`
- `AgentRuntime` (from `agent_runtime`), composed from a `ConversationStore`, the browser runtime, and the integration cache → `AGENT_RUNTIME_KEY`

Then all 23 `register_*_routes(app)` calls run (see [[API Routes]]) before the phased startup hooks below are appended.

## Phases

### Phase 1: Data Migrations + Routine Composition

- `_run_data_migrations(app)` runs synchronous migration scripts in `migrations/` against the state directory. Completes before any route handler runs.
- `_configure_routines(app)` composes `RoutineService`/`TaskExecutor`/`TaskRunner` (from `tasks`) against `config.routines` and stores them on the app (`ROUTINE_SERVICE_KEY`, `app["task_runner"]`). **Config and UI terminology is now "routines", not "goals"** — see [[Task Engine]]. If `config.routines.enabled` is false, a `RoutineService` with `runner=None` is stored instead, so routine-reading routes still work without a live runner.

### Phase 2: Readiness Signals

Two contributors register events that must all fire before deferred subsystems start:

- **Setup readiness** (`_init_setup_signal`): fires immediately if the setup wizard was already completed; waits if not.
- **Integrations readiness** (`_init_integrations_signal`): attempts to load the integrations cache (supervisor socket) with a 30-second deadline and exponential retry. Fires even on timeout so the app doesn't hang forever — chat works without integration tools.

`_init_ready_signal` aggregates both contributors into `app["ready"]`.

### Phase 3: Deferred Subsystems

`_start_deferred_subsystems` spawns a background task that awaits `app["ready"]`, then starts the `task_runner` (if one was composed in Phase 1 and routines are enabled).

### Shutdown

`on_cleanup` hooks, in registration order:
- `_stop_deferred_subsystems` — cancels the deferred-init task, stops the task runner
- `_stop_active_run_manager` — calls `app[AGENT_RUNTIME_KEY].close()`, gracefully stopping process-owned agent runs
- `_stop_integrations` — cancels startup waiters and closes the integration cache
- `_shutdown_executor` (registered in `main.py`, not `create_app()`) — gracefully drains thread-pool executors with a 5-second timeout; force-exits via `os._exit(0)` if they hang (avoids needing multiple Ctrl+C presses when something — e.g. a stuck Docker exec stream — is blocked on I/O)

`main.py` also owns `close_browser()`-equivalent cleanup is **not** present directly; browser teardown is reached through `AgentRuntime.close()` via the browser runtime stored at `BROWSER_RUNTIME_KEY`, not a standalone `close_browser()` call as the previous wiki pass described — re-verify this specific claim if browser lifecycle code changes again, it wasn't traced past `create_app()`.

## Readiness Pattern

The pattern allows adding new gating signals without touching the deferred-subsystem code:
1. Write `_init_my_signal(app)` startup hook that calls `register_ready_contributor(app, "my_name")` and signals the returned event when ready.
2. Register the hook in `create_app()` before `_init_ready_signal`.

## Related Entities

- [[API Routes]] — all routes registered in `create_app()`, and the app-level state (`AgentRuntime`, caches) described above
- [[Task Engine]] — started/composed in Phases 1 and 3
- [[Integrations Architecture]] — integrations readiness contributor

## Open Questions

- Exact browser-runtime shutdown path (`AgentRuntime.close()` internals) not traced — flagged above rather than asserted confidently.

## Sources

- `server/aiohttp_app.py`
- `main.py`
