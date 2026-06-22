---
title: "Source - Tasks Overview"
type: source
tags: [tasks, goals, scheduler, background, notifier]
created: 2026-06-22
updated: 2026-06-22
sources: []
---

# Source - Tasks Overview

## Summary

The `tasks/` package implements the autonomous task engine — a background runner that polls for scheduled goals and executes them using the agent loop. Goals are persistent, can recur on a schedule, and can contain multiple ordered tasks. The `TaskRunner` runs as an asyncio task inside the aiohttp server process (not a separate process), sharing the event loop, providers, and browser contexts with the chat agent.

## Key Points

**TaskRunner (`tasks/_runner.py`):**
- Asyncio task polling loop; started on app startup (after readiness signals)
- `_tick()`: spawns due recurring goal runs, picks up ready task results up to `max_concurrent`, cleans up finished tasks
- `pause()` / `resume()` — stop/start picking up new tasks without stopping the runner
- Retry logic: tasks retry up to `max_retries`; on final failure, marked failed
- Completion notifications via `TelegramNotifier` (if configured)

**TaskExecutor (`tasks/_executor.py`):**
- Executes a single task by running the agent loop with the task's description as the user message
- Returns `(result_text, file_paths)` tuple

**TaskStore (`tasks/_store.py`, `_file_store.py`):**
- Persistent goal/task/run/result storage (file-based under `{home_dir}/goals/`)
- `get_due_recurring_goals()`, `queue_run()`, `get_ready_task_results()`
- `reset_stale_running()` — on startup, resets any tasks stuck in "running" state (e.g., from a crash)

**Goal model:**
- Goals have descriptions, schedules, and ordered task lists
- Runs are instances of a goal's execution (run_number tracks recurrence)
- Each task in a run produces a TaskResult with status, result text, error, and file outputs

**TelegramNotifier (`tasks/_notifier.py`):**
- Sends formatted run completion/failure messages via Telegram bot API
- Includes file attachments if `include_files=True` (up to `max_attachment_size_mb`)
- Configurable per-event: `on_run_completed`, `on_run_failed`

**Agent tools for tasks:**
- `begin_goal`, `commit_goal`, `add_task`, `list_goals`, `list_tasks`, `trigger_goal`
- These are the LLM-callable tools the agent uses to create and manage goals

## Entities Mentioned

- [[TaskRunner]]
- [[TaskExecutor]]
- [[TaskStore]]
- [[TelegramNotifier]]
- [[GoalsConfig]]
- [[AgentProfile]]

## Concepts Covered

- [[Agent Loop]]
- [[Turn Lifecycle]]

## Raw Notes

- TaskRunner runs inside aiohttp process, not a separate process — simpler, shares event loop
- `GoalsConfig.max_concurrent` (default 2) limits parallel task executions
- `GoalsConfig.poll_interval` (default 5s) controls how often the runner checks for due work
- `GoalsConfig.shutdown_timeout` (default 60s) — how long to wait for running tasks on shutdown
- `GoalsConfig.timezone` (default "UTC") — timezone for cron-style schedule evaluation
- `get_store()` returns a lazily-initialized singleton `TaskStore`
