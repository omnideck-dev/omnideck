"""Routine policy adapter for the shared application scheduler."""
from __future__ import annotations

import asyncio
import logging
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from scheduling import ScheduledWork, Scheduler

if TYPE_CHECKING:
    from config import RoutinesConfig
    from tasks._executor import TaskExecutor
    from tasks._models import Task, TaskResult
    from tasks._notifier import TelegramNotifier
    from tasks._store import TaskStore

logger = logging.getLogger(__name__)


class RoutineWorkSource:
    """Supply routine tasks; keep dependency, retry and notification policy here."""
    name = "routines"

    def __init__(self, store: TaskStore, executor: TaskExecutor, config: RoutinesConfig, *,
                 scheduler: Scheduler, notifier: TelegramNotifier | None = None) -> None:
        self._store = store
        self._executor = executor
        self._config = config
        self._scheduler = scheduler
        self._notifier = notifier
        self._paused = False

    @property
    def enabled(self) -> bool:
        return not self._paused

    def recover(self) -> None:
        self._store.reset_stale_running()

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    @asynccontextmanager
    async def stop_routine(self, routine_id: str) -> AsyncIterator[None]:
        async with self._scheduler.block(self.name, "routine", routine_id):
            yield

    @asynccontextmanager
    async def stop_run(self, run_id: str) -> AsyncIterator[None]:
        async with self._scheduler.block(self.name, "run", run_id):
            yield

    @property
    def status(self) -> dict:
        active = self._scheduler.active(self.name)
        return {
            "running": self._scheduler.running and self.enabled,
            "paused": self._paused,
            "active_tasks": len(active),
            "max_concurrent": self._scheduler.max_concurrent,
            "running_routine_ids": list({entry.work.labels["routine"] for entry in active}),
        }

    def pending(self, now: datetime) -> list[ScheduledWork]:
        for routine in self._store.get_due_recurring_routines(now):
            if self._scheduler.blocked(self.name, {"routine": routine.id}):
                continue
            run = self._store.queue_run(routine.id)
            self._store.stamp_last_run_spawned(routine.id)
            logger.info("Spawned run #%d for routine %s", run.run_number, routine.id)
        return [ScheduledWork(
            id=result.id, target=f"routines/{task.routine_id}/{result.run_id}/{result.id}",
            due_at=now, labels={"routine": task.routine_id, "run": result.run_id},
            dispatch=partial(self._dispatch, result, task),
        ) for result, task in self._store.get_ready_task_results()]

    async def _dispatch(self, result: TaskResult, task: Task) -> asyncio.Future | None:
        if not self.enabled:
            return None
        self._store.mark_task_result_running(result.id)
        self._store.update_run_status(result.run_id)
        return asyncio.create_task(self._execute(result, task), name=f"scheduled-routine-{result.id}")

    async def _execute(self, task_result: "TaskResult", task: "Task") -> None:
        """Execute a task, recording outcome into its result."""
        try:
            result_text, file_paths = await self._executor.run(task_result, task)
            if file_paths:
                self._store.set_file_outputs(task_result.id, file_paths)
            self._store.mark_task_result_completed(task_result.id, result_text)
        except Exception:
            error_msg = traceback.format_exc()
            logger.exception("Task %s failed", task.description)

            if task_result.retry_count < task.max_retries:
                self._store.increment_retry(task_result.id, error_msg)
                self._store.update_task_result_status(task_result.id, "pending")
                logger.info(
                    "Task %s queued for retry (%d/%d)",
                    task.description,
                    task_result.retry_count + 1,
                    task.max_retries,
                )
            else:
                self._store.mark_task_result_failed(task_result.id, error_msg)

        new_status = self._store.update_run_status(task_result.run_id)
        if new_status in ("completed", "failed") and self._notifier:
            await self._notify_run_finished(task_result.run_id, new_status)

    async def _notify_run_finished(self, run_id: str, status: str) -> None:
        """Send a Telegram notification when a run reaches a terminal state."""
        from tasks._notifier import format_run_completed, format_run_failed

        cfg = self._config.notifications
        if status == "completed" and not cfg.on_run_completed:
            return
        if status == "failed" and not cfg.on_run_failed:
            return

        run = self._store.get_run(run_id)
        if not run:
            return
        routine = self._store.get_routine(run.routine_id)
        if not routine:
            return

        results = self._store.get_task_results(run_id)
        tasks = {t.id: t for t in self._store.list_tasks(run.routine_id)}
        completed_count = sum(1 for r in results if r.status == "completed")
        total_count = len(results)

        duration = ""
        if run.started_at and run.completed_at:
            try:
                start = datetime.fromisoformat(run.started_at)
                end = datetime.fromisoformat(run.completed_at)
                secs = int((end - start).total_seconds())
                duration = f"{secs // 60}m {secs % 60}s" if secs >= 60 else f"{secs}s"
            except (ValueError, TypeError):
                duration = ""

        # Collect file outputs from all completed tasks in this run
        all_files: list[Path] = []
        if cfg.include_files:
            for r in results:
                for fp in r.file_outputs:
                    p = Path(fp)
                    if p.is_file():
                        all_files.append(p)

        if status == "completed":
            # Use the last completed task's result as the final output
            last_result = ""
            for r in reversed(results):
                if r.status == "completed" and r.result:
                    last_result = r.result
                    break
            message = format_run_completed(
                routine_description=routine.description,
                run_number=run.run_number,
                duration=duration,
                total_tasks=total_count,
                completed_tasks=completed_count,
                final_output=last_result,
                file_count=len(all_files),
            )
        else:
            # Find the failed task
            failed_desc = "unknown"
            error = ""
            for r in results:
                if r.status == "failed":
                    task = tasks.get(r.task_id)
                    failed_desc = task.description if task else r.task_id
                    error = r.error or ""
                    break
            message = format_run_failed(
                routine_description=routine.description,
                run_number=run.run_number,
                duration=duration,
                total_tasks=total_count,
                completed_tasks=completed_count,
                failed_task_description=failed_desc,
                error=error,
            )

        assert self._notifier is not None  # Guarded by caller
        await self._notifier.send(message, all_files if all_files else None)


__all__ = ["RoutineWorkSource"]
