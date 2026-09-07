"""File-based TaskStore implementation using JSON files on disk."""

from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Callable
from pathlib import Path

from tasks._models import Routine, Run, Task, TaskResult, _new_id, _utcnow
from tasks._scheduler import cron_has_fired_since

logger = logging.getLogger(__name__)

ROUTINES_SUBDIR = "routines"


class FileTaskStore:
    """File-based TaskStore implementation.

    One JSON file per routine (containing task definitions), one JSON file per
    run (containing task results). Layout::

        {base_dir}/
        ├── {routine_id}.json
        └── {routine_id}/
            └── runs/
                └── {run_id}.json
    """

    def __init__(self, base_dir: Path, default_timezone: str = "UTC") -> None:
        self._base = base_dir
        self._base.mkdir(parents=True, exist_ok=True)
        self._default_timezone = default_timezone


    def _routine_path(self, routine_id: str) -> Path:
        return self._base / f"{routine_id}.json"

    def _runs_dir(self, routine_id: str) -> Path:
        return self._base / routine_id / "runs"

    def _run_path(self, routine_id: str, run_id: str) -> Path:
        return self._runs_dir(routine_id) / f"{run_id}.json"


    @staticmethod
    def _routine_from_data(data: dict) -> "Routine":
        return Routine(**{k: v for k, v in data.items() if k != "tasks"})

    @staticmethod
    def _run_from_data(data: dict) -> "Run":
        return Run(**{k: v for k, v in data.items() if k != "task_results"})


    def _write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        tmp.replace(path)

    def _read_json(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


    def create_routine(self, description: str, cron: str | None = None, timezone: str | None = None, auto_run: bool = True) -> Routine:
        """Create a new routine. One-shot routines (no cron) auto-spawn a run unless auto_run=False."""
        routine = Routine(description=description, cron=cron, timezone=timezone or self._default_timezone)
        data = routine.model_dump()
        data["tasks"] = []
        self._write_json(self._routine_path(routine.id), data)
        if auto_run and not cron:
            self.queue_run(routine.id)
        return routine

    def get_routine(self, routine_id: str) -> Routine | None:
        """Return a routine by ID, or None if not found."""
        data = self._read_json(self._routine_path(routine_id))
        if not data:
            return None
        return self._routine_from_data(data)

    def list_routines(self, status: str | None = None) -> list[Routine]:
        """List routines, optionally filtered by status."""
        routines = []
        for p in self._base.glob("*.json"):
            data = self._read_json(p)
            if data and (status is None or data.get("status") == status):
                routines.append(self._routine_from_data(data))
        return sorted(routines, key=lambda g: g.created_at, reverse=True)

    def set_routine_status(self, routine_id: str, status: str) -> None:
        """Update the status of a routine."""
        path = self._routine_path(routine_id)
        data = self._read_json(path)
        if data:
            data["status"] = status
            self._write_json(path, data)

    def delete_routine(self, routine_id: str) -> list[str]:
        """Delete routine and all runs. Returns conversation_ids for cleanup."""
        conv_ids: list[str] = []
        runs_dir = self._runs_dir(routine_id)
        if runs_dir.exists():
            for rp in runs_dir.glob("*.json"):
                run_data = self._read_json(rp)
                if run_data:
                    for tr in run_data.get("task_results", []):
                        if tr.get("conversation_id"):
                            conv_ids.append(tr["conversation_id"])
        routine_dir = self._base / routine_id
        if routine_dir.exists():
            shutil.rmtree(routine_dir)
        self._routine_path(routine_id).unlink(missing_ok=True)
        return conv_ids


    def create_task(
        self,
        routine_id: str,
        description: str,
        instruction: str,
        agent_profile: str | None = None,
        depends_on: list[str] | None = None,
    ) -> Task:
        """Create a task definition belonging to a routine."""
        td: dict = {
            "description": description,
            "instruction": instruction,
            "depends_on": depends_on or [],
        }
        if agent_profile:
            td["agent_profile"] = agent_profile
        return self.create_tasks(routine_id, [td])[0]

    def create_tasks(
        self,
        routine_id: str,
        task_defs: list[dict],
    ) -> list[Task]:
        """Create multiple task definitions in a single read-write cycle."""
        path = self._routine_path(routine_id)
        data = self._read_json(path)
        if not data:
            msg = f"Routine {routine_id} not found"
            raise ValueError(msg)
        created: list[Task] = []
        for td in task_defs:
            task = Task(routine_id=routine_id, **td)
            data["tasks"].append(task.model_dump())
            created.append(task)
        self._write_json(path, data)
        return created

    def list_tasks(self, routine_id: str) -> list[Task]:
        """List task definitions for a routine."""
        data = self._read_json(self._routine_path(routine_id))
        if not data:
            return []
        return [Task(**t) for t in data.get("tasks", [])]

    def get_task(self, task_id: str) -> Task | None:
        """Return a task by ID, or None if not found."""
        for p in self._base.glob("*.json"):
            data = self._read_json(p)
            if data:
                for t in data.get("tasks", []):
                    if t.get("id") == task_id:
                        return Task(**t)
        return None


    def queue_run(self, routine_id: str) -> Run:
        """Create a new run for a routine with TaskResults for each task."""
        existing = self.get_routine_runs(routine_id)
        run_number = max((r.run_number for r in existing), default=0) + 1

        run = Run(routine_id=routine_id, run_number=run_number)
        tasks = self.list_tasks(routine_id)
        task_results = [
            TaskResult(run_id=run.id, task_id=t.id).model_dump()
            for t in tasks
        ]

        run_data = run.model_dump()
        run_data["task_results"] = task_results
        self._write_json(self._run_path(routine_id, run.id), run_data)
        return run

    def stamp_last_run_spawned(self, routine_id: str) -> None:
        """Update the routine's last_run_spawned_at timestamp.

        Called by the scheduler when spawning a cron-triggered run so the
        anchor survives run deletion. Manual triggers should NOT call this.
        """
        path = self._routine_path(routine_id)
        data = self._read_json(path)
        if data:
            data["last_run_spawned_at"] = _utcnow()
            self._write_json(path, data)

    def get_run(self, run_id: str) -> Run | None:
        """Return a run by ID, or None if not found."""
        try:
            _, run_data, _ = self._find_run(run_id)
            return self._run_from_data(run_data)
        except ValueError:
            return None

    def get_routine_runs(self, routine_id: str) -> list[Run]:
        """List all runs for a routine."""
        runs_dir = self._runs_dir(routine_id)
        if not runs_dir.exists():
            return []
        runs = []
        for p in runs_dir.glob("*.json"):
            data = self._read_json(p)
            if data:
                runs.append(self._run_from_data(data))
        return sorted(runs, key=lambda r: r.run_number)

    def update_run_status(self, run_id: str) -> str:
        """Recompute run status from its task_results."""
        routine_id, run_data, run_path = self._find_run(run_id)
        task_results = run_data.get("task_results", [])

        # Cascade failures: if a pending task's dependency has failed, fail it too.
        # Loop until no more cascades are possible.
        tasks = {t.id: t for t in self.list_tasks(routine_id)}
        changed = True
        while changed:
            changed = False
            failed_task_ids = {tr["task_id"] for tr in task_results if tr["status"] == "failed"}
            for tr in task_results:
                if tr["status"] != "pending":
                    continue
                task = tasks.get(tr["task_id"])
                if task and any(dep in failed_task_ids for dep in task.depends_on):
                    tr["status"] = "failed"
                    tr["error"] = "Blocked: a dependency task failed"
                    tr["completed_at"] = _utcnow()
                    changed = True

        statuses = [tr["status"] for tr in task_results]

        if all(s == "completed" for s in statuses):
            new_status = "completed"
        elif any(s == "failed" for s in statuses) and not any(
            s in ("pending", "running") for s in statuses
        ):
            new_status = "failed"
        elif any(s == "running" for s in statuses):
            new_status = "running"
        else:
            new_status = "pending"

        run_data["status"] = new_status
        if new_status == "running" and not run_data.get("started_at"):
            run_data["started_at"] = _utcnow()
        if new_status in ("completed", "failed"):
            run_data["completed_at"] = _utcnow()
        self._write_json(run_path, run_data)
        return new_status

    def delete_run(self, run_id: str) -> list[str]:
        """Delete run and task_results. Returns conversation_ids for cleanup."""
        for routine_dir in self._base.iterdir():
            if not routine_dir.is_dir():
                continue
            run_path = routine_dir / "runs" / f"{run_id}.json"
            if run_path.exists():
                data = self._read_json(run_path)
                if data is None:
                    return []
                conv_ids = [
                    tr["conversation_id"]
                    for tr in data.get("task_results", [])
                    if tr.get("conversation_id")
                ]
                run_path.unlink()
                return conv_ids
        return []


    def get_task_results(self, run_id: str) -> list[TaskResult]:
        """Get all task results for a run."""
        try:
            _, run_data, _ = self._find_run(run_id)
        except ValueError:
            return []
        return [TaskResult(**tr) for tr in run_data.get("task_results", [])]

    def get_ready_task_results(self) -> list[tuple[TaskResult, Task]]:
        """Pending results (deps met) in any routine's in-progress runs.

        Not limited to active routines: pausing a routine only stops its cron
        scheduling (see get_due_recurring_routines), not the execution of a run
        that was manually triggered or already in flight when it was paused.
        """
        ready: list[tuple[TaskResult, Task]] = []
        for routine in self.list_routines():
            tasks = {t.id: t for t in self.list_tasks(routine.id)}
            for run in self.get_routine_runs(routine.id):
                if run.status not in ("pending", "running"):
                    continue
                run_data = self._read_json(self._run_path(routine.id, run.id))
                if not run_data:
                    continue
                results = run_data.get("task_results", [])
                completed_task_ids = {
                    tr["task_id"] for tr in results if tr["status"] == "completed"
                }
                for tr_data in results:
                    if tr_data["status"] != "pending":
                        continue
                    task = tasks.get(tr_data["task_id"])
                    if not task:
                        continue
                    if all(dep_id in completed_task_ids for dep_id in task.depends_on):
                        ready.append((TaskResult(**tr_data), task))
        return ready

    def mark_task_result_running(self, result_id: str) -> None:
        """Mark a task result as running."""
        self._mutate_task_result(
            result_id,
            lambda tr: tr.update(status="running", started_at=_utcnow()),
        )

    def mark_task_result_completed(self, result_id: str, result: str) -> None:
        """Mark a task result as completed with its result text."""
        self._mutate_task_result(
            result_id,
            lambda tr: tr.update(status="completed", result=result, completed_at=_utcnow()),
        )

    def mark_task_result_failed(self, result_id: str, error: str) -> None:
        """Mark a task result as failed with an error message."""
        self._mutate_task_result(
            result_id,
            lambda tr: tr.update(status="failed", error=error, completed_at=_utcnow()),
        )

    def increment_retry(self, result_id: str, error: str) -> None:
        """Increment retry count and record the error."""
        self._mutate_task_result(
            result_id,
            lambda tr: tr.update(retry_count=tr.get("retry_count", 0) + 1, error=error),
        )

    def update_task_result_status(self, result_id: str, status: str) -> None:
        """Update the status of a task result."""
        self._mutate_task_result(
            result_id,
            lambda tr: tr.update(status=status),
        )

    def set_agent_run(self, result_id: str, *, conversation_id: str, agent_run_id: str) -> None:
        """Set the conversation ID for a task result."""
        self._mutate_task_result(
            result_id,
            lambda tr: tr.update(conversation_id=conversation_id, agent_run_id=agent_run_id),
        )

    def set_file_outputs(self, result_id: str, file_outputs: list[str]) -> None:
        """Set the file output paths for a task result."""
        self._mutate_task_result(
            result_id,
            lambda tr: tr.update(file_outputs=file_outputs),
        )

    def get_completed_results_for_tasks(
        self, run_id: str, task_ids: list[str]
    ) -> list[tuple[str, str]]:
        """Returns (task.description, result_text) for completed deps in a run."""
        routine_id, run_data, _ = self._find_run(run_id)
        tasks = {t.id: t for t in self.list_tasks(routine_id)}
        results: list[tuple[str, str]] = []
        for tr in run_data.get("task_results", []):
            if (
                tr["task_id"] in task_ids
                and tr["status"] == "completed"
                and tr.get("result")
            ):
                task = tasks.get(tr["task_id"])
                if task:
                    results.append((task.description, tr["result"]))
        return results


    def get_due_recurring_routines(self) -> list[Routine]:
        """Active routines with cron, no in-progress run, and cron due since last run."""
        result: list[Routine] = []
        for routine in self.list_routines(status="active"):
            if not routine.cron:
                continue
            runs = self.get_routine_runs(routine.id)
            # Skip if any run is still in progress
            if any(r.status in ("pending", "running") for r in runs):
                continue
            last_completed = max(
                (r.completed_at for r in runs if r.completed_at), default=None
            )
            anchor = last_completed or routine.last_run_spawned_at or routine.created_at
            if cron_has_fired_since(routine.cron, anchor, routine.timezone):
                result.append(routine)
        return result


    def reset_stale_running(self) -> None:
        """Reset task_results stuck in 'running' back to 'pending', then cascade failures."""
        for routine_dir in self._base.iterdir():
            if not routine_dir.is_dir():
                continue
            runs_dir = routine_dir / "runs"
            if not runs_dir.exists():
                continue
            tasks = {t.id: t for t in self.list_tasks(routine_dir.name)}
            for run_path in runs_dir.glob("*.json"):
                data = self._read_json(run_path)
                if not data:
                    continue
                if data.get("status") not in ("pending", "running"):
                    continue
                changed = False
                for tr in data.get("task_results", []):
                    if tr["status"] == "running":
                        tr["status"] = "pending"
                        tr["started_at"] = None
                        changed = True

                # Cascade failures for pending tasks whose deps have failed.
                task_results = data.get("task_results", [])
                cascade = True
                while cascade:
                    cascade = False
                    failed_ids = {tr["task_id"] for tr in task_results if tr["status"] == "failed"}
                    for tr in task_results:
                        if tr["status"] != "pending":
                            continue
                        task = tasks.get(tr["task_id"])
                        if task and any(dep in failed_ids for dep in task.depends_on):
                            tr["status"] = "failed"
                            tr["error"] = "Blocked: a dependency task failed"
                            tr["completed_at"] = _utcnow()
                            changed = True
                            cascade = True

                if changed:
                    # Recompute run status
                    statuses = [tr["status"] for tr in task_results]
                    if all(s == "completed" for s in statuses):
                        data["status"] = "completed"
                    elif any(s == "failed" for s in statuses) and not any(
                        s in ("pending", "running") for s in statuses
                    ):
                        data["status"] = "failed"
                        if not data.get("completed_at"):
                            data["completed_at"] = _utcnow()
                    elif any(s == "running" for s in statuses):
                        data["status"] = "running"
                    else:
                        data["status"] = "pending"
                    self._write_json(run_path, data)


    def _find_run(self, run_id: str) -> tuple[str, dict, Path]:
        """Locate a run file by run_id.

        Returns:
            Tuple of (routine_id, run_data, run_path).

        Raises:
            ValueError: If the run is not found.
        """
        for routine_dir in self._base.iterdir():
            if not routine_dir.is_dir():
                continue
            run_path = routine_dir / "runs" / f"{run_id}.json"
            if run_path.exists():
                data = self._read_json(run_path)
                if data is not None:
                    return routine_dir.name, data, run_path
        raise ValueError(f"Run {run_id} not found")

    def _mutate_task_result(self, result_id: str, fn: Callable[[dict], None]) -> None:
        """Find a task_result by ID across all runs, apply mutation, save."""
        for routine_dir in self._base.iterdir():
            if not routine_dir.is_dir():
                continue
            runs_dir = routine_dir / "runs"
            if not runs_dir.exists():
                continue
            for run_path in runs_dir.glob("*.json"):
                data = self._read_json(run_path)
                if not data:
                    continue
                for tr in data.get("task_results", []):
                    if tr["id"] == result_id:
                        fn(tr)
                        self._write_json(run_path, data)
                        return


__all__ = ["FileTaskStore"]
