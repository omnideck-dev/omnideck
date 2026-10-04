"""Atomic persistence and explicit state transitions for conversation goals."""

from __future__ import annotations

import builtins
import os
import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import ClassVar
from uuid import uuid4

from ._models import Goal, GoalKind, GoalProgress, TERMINAL_STATUSES, utc_now, utc_timestamp

GOALS_SUBDIR = "session-goals"


class GoalConflictError(ValueError):
    """A goal revision or execution owner no longer matches the caller."""


class GoalNotFoundError(KeyError):
    """The requested goal does not exist."""


class GoalStateError(ValueError):
    """The requested action is unavailable in the goal's current state."""


class GoalStore:
    """Persist goals and their wakes as one atomic record per goal."""

    _locks: ClassVar[dict[Path, RLock]] = {}
    _locks_guard: ClassVar[RLock] = RLock()

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir.resolve()
        with self._locks_guard:
            self._lock = self._locks.setdefault(self._base, RLock())

    def _path(self, goal_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", goal_id):
            raise ValueError("Invalid goal ID")
        return self._base / f"{goal_id}.json"

    def _write(self, goal: Goal) -> Goal:
        validated = Goal.model_validate(goal.model_dump())
        self._base.mkdir(parents=True, exist_ok=True)
        target = self._path(goal.id)
        temporary = target.with_name(f".{goal.id}.{uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                stream.write(validated.model_dump_json(indent=2))
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return validated

    def get(self, goal_id: str) -> Goal | None:
        with self._lock:
            path = self._path(goal_id)
            if not path.exists():
                return None
            return Goal.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> builtins.list[Goal]:
        with self._lock:
            goals = [Goal.model_validate_json(path.read_text(encoding="utf-8")) for path in self._base.glob("*.json")]
            return sorted(goals, key=lambda goal: goal.created_at, reverse=True)

    def history(self, conversation_id: str) -> builtins.list[Goal]:
        return [goal for goal in self.list() if goal.conversation_id == conversation_id]

    def current(self, conversation_id: str) -> Goal | None:
        return next((goal for goal in self.history(conversation_id) if goal.status not in TERMINAL_STATUSES), None)

    def latest(self, conversation_id: str) -> Goal | None:
        return next(iter(self.history(conversation_id)), None)

    def create(
        self, conversation_id: str, objective: str, profile_id: str, *, kind: GoalKind = "finite",
        constraints: str = "", success_criteria: builtins.list[str] | None = None,
    ) -> Goal:
        with self._lock:
            if self.current(conversation_id.strip()) is not None:
                raise GoalConflictError("This conversation already has an unfinished goal")
            goal = Goal(
                conversation_id=conversation_id, objective=objective, profile_id=profile_id, kind=kind,
                constraints=constraints, success_criteria=success_criteria or [],
                wake_id=uuid4().hex, resume_at=utc_now(), wake_reason="Goal assigned",
                next_action="Review the goal and create or update the plan.",
            )
            return self._write(goal)

    def _require(self, goal_id: str) -> Goal:
        goal = self.get(goal_id)
        if goal is None:
            raise GoalNotFoundError(f"Goal '{goal_id}' not found")
        return goal

    def _mutate(
        self, goal_id: str, change: Callable[[Goal], None], *, expected_revision: int | None = None,
        claim_id: str | None = None, allow_terminal: bool = False,
    ) -> Goal:
        with self._lock:
            goal = self._require(goal_id)
            if expected_revision is not None and goal.revision != expected_revision:
                raise GoalConflictError(f"Goal changed; read revision {goal.revision} before updating")
            if not allow_terminal and goal.status in TERMINAL_STATUSES:
                raise GoalStateError("This goal has ended")
            if claim_id is not None:
                if goal.claimed_run_id != claim_id:
                    raise GoalConflictError("This execution no longer owns the goal")
                if goal.status == "paused":
                    raise GoalStateError("This goal is paused")
            change(goal)
            goal.revision += 1
            goal.updated_at = utc_now()
            return self._write(goal)

    def update(self, goal_id: str, expected_revision: int, *, claim_id: str | None = None, **fields: object) -> Goal:
        allowed = {"objective", "kind", "profile_id", "constraints", "success_criteria", "plan", "next_action"}
        if fields.keys() - allowed:
            raise ValueError("Only objective, kind, profile, constraints, success criteria, plan, and next action are editable")

        def change(goal: Goal) -> None:
            updated = Goal.model_validate({**goal.model_dump(), **fields})
            for name in fields:
                setattr(goal, name, getattr(updated, name))

        return self._mutate(goal_id, change, expected_revision=expected_revision, claim_id=claim_id)

    @staticmethod
    def _clear_wake(goal: Goal) -> None:
        goal.wake_id = None
        goal.resume_at = None
        goal.wake_reason = None

    @staticmethod
    def _clear_claim(goal: Goal) -> None:
        goal.claimed_run_id = None
        goal.claimed_wake_id = None
        goal.claimed_resume_at = None
        goal.claimed_wake_reason = None
        goal.claimed_next_action = None
        goal.claim_revision = None

    @staticmethod
    def _queue(goal: Goal, when: str, reason: str, next_action: str) -> None:
        goal.wake_id = uuid4().hex
        goal.resume_at = when
        goal.wake_reason = reason
        goal.next_action = next_action
        goal.status_reason = reason

    def pause(self, goal_id: str, *, expected_revision: int | None = None) -> Goal:
        def change(goal: Goal) -> None:
            goal.status = "paused"
            goal.status_reason = "Paused by user"
            self._clear_wake(goal)
            self._clear_claim(goal)
        return self._mutate(goal_id, change, expected_revision=expected_revision)

    def resume(self, goal_id: str, *, expected_revision: int | None = None) -> Goal:
        def change(goal: Goal) -> None:
            if goal.claimed_run_id is not None:
                raise GoalConflictError("The goal already has an active execution")
            goal.status = "active"
            self._queue(goal, utc_now(), "Resumed by user", goal.next_action or "Review saved progress and continue the goal.")
        return self._mutate(goal_id, change, expected_revision=expected_revision)

    def cancel(self, goal_id: str, *, expected_revision: int | None = None) -> Goal:
        def change(goal: Goal) -> None:
            goal.status = "cancelled"
            goal.status_reason = "Cancelled by user"
            self._clear_wake(goal)
            self._clear_claim(goal)
        return self._mutate(goal_id, change, expected_revision=expected_revision)

    def schedule(
        self, goal_id: str, resume_at: str, reason: str, next_action: str, *,
        claim_id: str | None = None, expected_revision: int | None = None, immediate: bool = False,
    ) -> Goal:
        when = utc_timestamp(resume_at)
        if not immediate and datetime.fromisoformat(when) <= datetime.now(timezone.utc):
            raise ValueError("Resume time must be in the future; use continue_goal to continue immediately")
        if not reason.strip() or not next_action.strip():
            raise ValueError("A reason and next action are required")

        def change(goal: Goal) -> None:
            if goal.status == "paused":
                raise GoalStateError("Resume the paused goal before scheduling it")
            goal.status = "active" if immediate else "scheduled"
            self._queue(goal, when, reason.strip(), next_action.strip())
        return self._mutate(goal_id, change, expected_revision=expected_revision, claim_id=claim_id)

    def wait_for_input(
        self, goal_id: str, reason: str, *, claim_id: str | None = None, expected_revision: int | None = None,
    ) -> Goal:
        if not reason.strip():
            raise ValueError("Explain what input is needed")

        def change(goal: Goal) -> None:
            goal.status = "needs_input"
            goal.status_reason = reason.strip()
            self._clear_wake(goal)
        return self._mutate(goal_id, change, expected_revision=expected_revision, claim_id=claim_id)

    def complete(
        self, goal_id: str, outcome: str, *, claim_id: str | None = None, expected_revision: int | None = None,
    ) -> Goal:
        if not outcome.strip():
            raise ValueError("Describe the completed outcome")

        def change(goal: Goal) -> None:
            goal.status = "completed"
            goal.outcome = outcome.strip()
            goal.status_reason = outcome.strip()
            self._clear_wake(goal)
        return self._mutate(goal_id, change, expected_revision=expected_revision, claim_id=claim_id)

    def record_progress(
        self, goal_id: str, summary: str, next_action: str = "", *,
        claim_id: str | None = None, expected_revision: int | None = None,
    ) -> Goal:
        if not summary.strip():
            raise ValueError("Progress summary cannot be blank")

        def change(goal: Goal) -> None:
            goal.progress.append(GoalProgress(summary=summary.strip(), next_action=next_action.strip()))
            goal.next_action = next_action.strip()
        return self._mutate(goal_id, change, expected_revision=expected_revision, claim_id=claim_id)

    def due(self, now: datetime | str | None = None) -> builtins.list[Goal]:
        timestamp = utc_timestamp(now) if now is not None else utc_now()
        return [goal for goal in self.list() if goal.status in {"active", "scheduled"}
                and goal.claimed_run_id is None and goal.resume_at is not None and goal.resume_at <= timestamp]

    def claim(self, goal_id: str, wake_id: str, claim_id: str, now: datetime | str | None = None) -> Goal | None:
        timestamp = utc_timestamp(now) if now is not None else utc_now()
        with self._lock:
            goal = self.get(goal_id)
            if (goal is None or goal.status not in {"active", "scheduled"} or goal.claimed_run_id is not None
                    or goal.wake_id != wake_id or goal.resume_at is None or goal.resume_at > timestamp):
                return None
            return self._claim(goal, claim_id)

    def _claim(self, goal: Goal, claim_id: str, *, preserve_wake: bool = False) -> Goal:
        if not claim_id:
            raise ValueError("Claim ID is required")
        goal.claimed_run_id = claim_id
        goal.claimed_wake_id = goal.wake_id
        goal.claimed_resume_at = goal.resume_at
        goal.claimed_wake_reason = goal.wake_reason
        goal.claimed_next_action = goal.next_action
        if not preserve_wake:
            goal.status = "active"
            self._clear_wake(goal)
        goal.revision += 1
        goal.claim_revision = goal.revision
        goal.updated_at = utc_now()
        return self._write(goal)

    def claim_for_turn(self, goal_id: str, claim_id: str) -> Goal | None:
        with self._lock:
            goal = self.get(goal_id)
            if goal is None or goal.status not in {"active", "scheduled", "needs_input"} or goal.claimed_run_id is not None:
                return None
            # A user turn can manage the goal without replacing an already
            # requested future wake. Due work is consumed by this turn instead.
            preserve_wake = goal.resume_at is not None and goal.resume_at > utc_now()
            return self._claim(goal, claim_id, preserve_wake=preserve_wake)

    def bind_run(self, goal_id: str, claim_id: str, run_id: str) -> Goal | None:
        with self._lock:
            goal = self.get(goal_id)
            if goal is None or goal.claimed_run_id != claim_id:
                return None
            goal.last_run_id = run_id
            goal.updated_at = utc_now()
            # Binding metadata does not alter the agent's disposition or the requeue guard.
            return self._write(goal)

    def release(self, goal_id: str, claim_id: str) -> Goal | None:
        with self._lock:
            goal = self.get(goal_id)
            if goal is None or goal.claimed_run_id != claim_id:
                return None
            self._clear_claim(goal)
            goal.revision += 1
            goal.updated_at = utc_now()
            return self._write(goal)

    def requeue_claim(self, goal_id: str, claim_id: str) -> Goal | None:
        with self._lock:
            goal = self.get(goal_id)
            if (goal is None or goal.claimed_run_id != claim_id or goal.status != "active"
                    or goal.revision != goal.claim_revision or goal.claimed_wake_id is None):
                return None
            goal.wake_id = goal.claimed_wake_id
            goal.resume_at = goal.claimed_resume_at
            goal.wake_reason = goal.claimed_wake_reason
            goal.next_action = goal.claimed_next_action or ""
            self._clear_claim(goal)
            goal.revision += 1
            goal.updated_at = utc_now()
            return self._write(goal)

    def recover_claims(self) -> builtins.list[Goal]:
        recovered = []
        with self._lock:
            for goal in self.list():
                if goal.claimed_run_id is None:
                    continue
                if goal.status == "active" and goal.wake_id is None:
                    self._queue(
                        goal, utc_now(), goal.claimed_wake_reason or "Execution interrupted",
                        "Execution interrupted; inspect saved progress and external state before repeating actions.",
                    )
                self._clear_claim(goal)
                goal.revision += 1
                goal.updated_at = utc_now()
                recovered.append(self._write(goal))
        return recovered

    def finish_run(
        self, goal_id: str, claim_id: str, run_id: str, status: str, error: str | None = None,
    ) -> Goal | None:
        with self._lock:
            goal = self.get(goal_id)
            if goal is None or goal.claimed_run_id != claim_id:
                return None
            goal.last_run_id = run_id
            if status == "error" and goal.status == "active" and goal.wake_id is None:
                goal.status = "needs_input"
                goal.status_reason = error or "The goal execution failed. Review the error before resuming."
            self._clear_claim(goal)
            goal.revision += 1
            goal.updated_at = utc_now()
            return self._write(goal)

    def delete_for_conversation(self, conversation_id: str) -> None:
        with self._lock:
            for goal in self.history(conversation_id):
                self._path(goal.id).unlink(missing_ok=True)
