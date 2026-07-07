---
title: Task Engine
type: entity
tags: [tasks, goals, routines, autonomous, scheduling]
created: 2026-07-07
updated: 2026-07-07
verified_commit: 6a5625d
paths:
  - "tasks/"
---

# Task Engine

## Overview

The Task Engine (also called the Goals or Routines system) enables autonomous background execution. Tasks (goals) have a name, a natural-language prompt, a cron-style schedule, and a reference to an `AgentProfile`. The `TaskRunner` polls for due tasks and executes them via the same SDK turn loop used for chat — no separate agent code path.

## Location

`tasks/` package. Started during server startup in `server/aiohttp_app.py:_init_task_runner()`, which waits for the readiness signal before launching.

## Components

| Module | Role |
|--------|------|
| `tasks/_runner.py:TaskRunner` | Main loop: polls `TaskStore`, dispatches due tasks to `TaskExecutor` |
| `tasks/_executor.py:TaskExecutor` | Runs a single task as a full agent turn |
| `tasks/_store.py:TaskStore` | In-memory store with disk persistence |
| `tasks/_file_store.py` | JSON file persistence for tasks |
| `tasks/_scheduler.py` | Cron evaluation — determines which tasks are due |
| `tasks/_models.py` | `Task`, `GoalRun` Pydantic models |
| `tasks/_notifier.py:TelegramNotifier` | Optional push notification on run completion/failure |
| `tasks/_singleton.py:get_store()` | Lazy-initialized singleton `TaskStore` |
| `tasks/_tools.py` | LLM-callable tools: `list_goals`, `add_task`, `trigger_goal`, etc. |

## Lifecycle

1. `TaskRunner.start()` spawns a background asyncio task that polls every N seconds (configurable via `GoalsConfig.poll_interval`)
2. On each poll, `_scheduler` evaluates which tasks' cron expressions are currently due
3. Due tasks are submitted to `TaskExecutor.run(task)`
4. `TaskExecutor` builds an `Agent` from the task's profile, calls `run_turn()` with the task prompt
5. Run outcome (success/error) is saved to `GoalRun` history
6. If configured, `TelegramNotifier` sends a push notification

Concurrency is bounded by `GoalsConfig.max_concurrent` (default 2).

## Agent Tools for Task Management

The LLM can manage tasks via tool calls:

| Tool | Description |
|------|-------------|
| `list_goals` | List all goals and their schedule/status |
| `add_task` | Create a new goal |
| `begin_goal` / `commit_goal` | Start and commit a goal run (internal lifecycle) |
| `trigger_goal` | Run a goal immediately (bypass schedule) |
| `list_tasks` | List tasks within a running goal |

## Related Entities

- [[AgentProfile]] — each task references a profile
- [[Turn Lifecycle]] — tasks execute via the same turn loop
- [[AppConfig]] — `GoalsConfig` controls enable/disable, poll interval, notifications

## Sources

- `tasks/__init__.py`
