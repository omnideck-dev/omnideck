---
title: TaskRunner
type: entity
tags: [tasks, background, scheduler, asyncio]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - Tasks Overview]]"]
---

# TaskRunner

## Overview

`TaskRunner` (in `tasks/_runner.py`) is the background asyncio task that polls for scheduled goals and executes them. It runs inside the aiohttp server process (not separately), sharing the event loop, providers, and browser contexts with the chat agent. It is started after all readiness signals are set (setup complete + integrations ready).

## Details

**Constructor:** `TaskRunner(store, executor, config, notifier=None)`

**Lifecycle:**
- `start()` — called by `_init_task_runner()` on app startup; resets stale "running" tasks from previous crash; starts `_poll_loop()` asyncio task
- `stop()` — called on app cleanup; sets stop event, waits up to `config.shutdown_timeout` for running tasks

**Poll loop:**
- Wakes every `config.poll_interval` seconds (default 5s)
- `_tick()`: spawn due recurring goal runs, pick up pending task results (up to `max_concurrent`), clean up finished tasks

**Execution:** delegates to `TaskExecutor.run(task_result, task)` → `(result_text, file_paths)` tuple

**Retry logic:** tasks retry up to `task.max_retries`; on final failure, marked failed

**Notifications:** after each run reaches terminal state (completed/failed), optionally sends Telegram message via `TelegramNotifier`

**Status API:** `runner.status` property returns running/paused/active_tasks/max_concurrent/running_goal_ids

**Pause/resume:** `pause()` / `resume()` — stop/start picking up new tasks without stopping the runner

## Related Entities

- [[TaskExecutor]]
- [[TaskStore]]
- [[TelegramNotifier]]
- [[GoalsConfig]] (poll_interval, max_concurrent, shutdown_timeout)
- [[AppConfig]] (`goals.enabled` flag)
- [[AgentLoop]] (executor uses it)

## Sources

- [[Source - Tasks Overview]]
