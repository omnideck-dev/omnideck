---
title: Task Engine
type: entity
tags: [tasks, routines, autonomous, scheduling, cron]
created: 2026-07-07
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "tasks/"
---

# Task Engine

## Overview

The Task Engine (the UI calls these **Routines**; the code dropped the older "Goals"
name — see `migrations/_013_goals_to_routines.py`) runs multi-step, scheduled or
on-demand work without a human in the loop. A **Routine** is an immutable description
of what to accomplish, optionally on a cron schedule; each **Run** of a routine executes
a DAG of **Tasks**, where each task is a single agent turn with its own agent profile
and its own retry policy. This is a real rewrite from the single-task "Goal" model the
wiki previously described — the current model supports dependency chains between
tasks within one run.

## Location

`tasks/` package. Started during server startup (see [[App Startup]]), which waits for
readiness before launching the poll loop.

## Data model (`tasks/_models.py`)

| Model | Role |
|-------|------|
| `Routine` | Immutable template: `description`, `status` (`active`/`paused`), optional `cron` + `timezone`, `last_run_spawned_at`. |
| `Task` | Immutable unit of work belonging to a routine: `description`, `instruction`, `agent_profile`, `depends_on` (task ids), `max_retries` (default 3). |
| `Run` | One execution of a routine: `run_number`, `status` (`pending`/`running`/`completed`/`failed`). |
| `TaskResult` | Per-run execution state for one task: `status`, `result`, `error`, `retry_count`, `conversation_id`, `agent_run_id`, `file_outputs`. |

A routine's tasks form a DAG via `depends_on`; a task only becomes "ready" once all of
its dependencies' results are `completed` within the same run.

## Components

| Module | Role |
|--------|------|
| `tasks/_runner.py:TaskRunner` | Background asyncio loop: polls for due routines and ready tasks, admits up to `max_concurrent` at a time, retries or fails on error, notifies on terminal run state. |
| `tasks/_executor.py:TaskExecutor` | Bridges one `TaskResult` + `Task` to an actual agent turn via `agent_runtime.AgentRuntime`. |
| `tasks/_store.py:TaskStore` | `Protocol` defining the storage contract (routines, tasks, runs, task results). |
| `tasks/_file_store.py:FileTaskStore` | The only implementation — one JSON file per routine/run under the routines directory. |
| `tasks/_scheduler.py:cron_has_fired_since` | Cron evaluation (via `croniter`), timezone-aware. |
| `tasks/_notifier.py:TelegramNotifier` | Optional push notification on run completion/failure, with file attachments. |
| `tasks/_service.py:RoutineService` | Coordinates deletion: stops a routine's/run's in-flight work via the runner before removing its persisted state, so a delete can't race a running task. |
| `tasks/_singleton.py:get_store()` | Lazily-initialized process-wide `FileTaskStore`, rooted at `RoutinesConfig.routines_dir` (default: under the home dir). |
| `tasks/_tools.py` | LLM-callable tools agents use to define and manage routines (see below). |

## Lifecycle

1. `TaskRunner.start()` resets any `running`-status task results left over from an
   unclean shutdown (`reset_stale_running`), then spawns `_poll_loop()`.
2. Each tick (`RoutinesConfig.poll_interval` seconds): spawn a new `Run` for every
   routine whose cron has fired since its last spawn; pull every task result whose
   dependencies are satisfied and whose routine/run isn't blocked; admit up to
   `max_concurrent` of them as `asyncio.Task`s running `TaskExecutor.run()`.
3. `TaskExecutor` builds the task's agent instruction (routine description + task
   instruction + any dependency results, injected as `## Results from previous tasks`),
   starts an `AgentRuntime` run with `RunPolicy(conversation_lifetime="run",
   restore_skills=False, persist_skills=False, include_memory=False)`, and awaits it.
   The conversation id is namespaced `routines/{routine_id}/{run_id}/{task_result_id}`.
4. On success: result text + any file artifacts are recorded. On failure: retried up to
   `max_retries` (requeued as `pending`), or marked `failed` once exhausted.
5. When a run reaches a terminal state (`completed`/`failed`), `TelegramNotifier` sends
   a push notification if configured (`RoutinesConfig.notifications`), including a
   summary and optionally attached output files.
6. `TaskRunner.stop_routine(routine_id)` / `stop_run(run_id)` are async context managers
   that cancel in-flight work and block new admissions for their scope until the caller
   exits — used by `RoutineService` before deleting persisted state.

Concurrency is bounded by `RoutinesConfig.max_concurrent` (default 2); polling cadence
by `RoutinesConfig.poll_interval` (default 5s). See [[Settings]] for where
routine-affecting config lives vs. per-routine state.

## Agent tools for routine authoring (`tasks/_tools.py`)

Routines are authored by an agent through a draft-then-commit flow, not created
directly as a `Routine` object:

| Tool | Role |
|------|------|
| `begin_routine(description, cron=None, timezone=None)` | Start a draft dict; validates the cron expression and timezone up front. |
| `add_task(draft, key, description, instruction, agent_profile, depends_on=None)` | Append a task to the draft. Omitting `depends_on` chains sequentially onto the previous task; `depends_on=[]` runs in parallel with no dependencies. Validates the agent profile exists and is enabled. |
| `commit_routine(draft)` | Validates the whole draft (unique keys, dependencies reference earlier tasks, valid profiles) and persists it; also queues the first run immediately if the routine has no cron. |
| `list_routines(status=None)` | List routines, optionally filtered by status. |
| `list_tasks(routine_id)` | List a routine's task definitions. |
| `trigger_routine(routine_id)` | Manually queue a new run regardless of schedule. |

## Related Entities

- [[AgentProfile]] — each task references one by id
- [[Turn Lifecycle]] — a task executes as one agent run through `agent_runtime`, the same machinery as interactive chat
- [[ConversationHistory]] — task runs use `transient=True`, non-persisted-skill conversation scopes
- [[Settings]] / `AppConfig.routines` (`RoutinesConfig`) — enable/disable, poll interval, concurrency, timezone, notifications

## Sources

- `migrations/_013_goals_to_routines.py` — confirms the Goals → Routines rename
