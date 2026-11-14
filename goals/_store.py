"""Atomic persistence and explicit state transitions for conversation goals."""

from __future__ import annotations

import builtins
import logging
import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import ClassVar

from pydantic import ValidationError

from ._models import (
    AcceptedGoalAnswer, CompleteChoice, ContinueChoice, Goal, GoalAnswer, GoalAnswerSubmission, GoalCancelled,
    GoalChoice, GoalClaim, GoalDone, GoalError, GoalHistoryEntry, GoalQuestion, GoalQuestionChange, GoalStep,
    GoalStepChange, GoalWait, GoalWake, HistoryActor, ScheduleChoice, apply_step_changes, has_open_step, local_time,
    utc_now, utc_timestamp,
)

from ._files import GoalFiles

logger = logging.getLogger(__name__)

GOALS_SUBDIR = "session-goals"
NO_OPEN_STEP = "Mark the step the next run should work on as in progress, or add one."


def validation_message(exc: ValidationError) -> str:
    """The first validation problem as a plain sentence."""
    message = str(exc.errors()[0].get("msg", exc))
    return message.removeprefix("Value error, ")


class GoalConflictError(ValueError):
    """A goal revision or execution owner no longer matches the caller."""


class GoalRevisionError(GoalConflictError):
    """Someone else changed the goal after the caller last read it."""


class GoalNotFoundError(KeyError):
    """The requested goal does not exist."""


class GoalStateError(ValueError):
    """The requested action is unavailable in the goal's current state."""


class GoalStore:
    """Persist current state and historical events as readable files.

    Unfinished goals are also kept in memory, shared by every store on the same
    folder, so the scheduler can find due wakes without reading every file.
    """

    _locks: ClassVar[dict[Path, RLock]] = {}
    _open_goals: ClassVar[dict[Path, dict[str, Goal]]] = {}
    _locks_guard: ClassVar[RLock] = RLock()

    def __init__(self, base_dir: Path) -> None:
        self._observers: list[Callable[[Goal, builtins.list[GoalHistoryEntry]], None]] = []
        self._base = base_dir.resolve()
        with self._locks_guard:
            self._lock = self._locks.setdefault(self._base, RLock())
        with self._lock:
            self._files = GoalFiles(self._base)

    def subscribe(self, observer: Callable[[Goal, builtins.list[GoalHistoryEntry]], None]) -> Callable[[], None]:
        """Observe committed changes and return a subscription cleanup."""
        self._observers.append(observer)
        return lambda: self._observers.remove(observer)

    def load(self) -> None:
        """Read every saved goal once to find the unfinished ones."""
        with self._lock:
            self._open_goals[self._base] = {goal.id: goal for goal in self._files.list() if not goal.ended}

    def _open(self) -> dict[str, Goal]:
        with self._lock:
            if self._base not in self._open_goals:
                self.load()
            return self._open_goals[self._base]

    def _remember(self, goal: Goal) -> None:
        index = self._open()
        if goal.ended:
            index.pop(goal.id, None)
        else:
            index[goal.id] = goal.model_copy(deep=True)

    def _notify(self, goal: Goal, entries: builtins.list[GoalHistoryEntry]) -> None:
        for observer in tuple(self._observers):
            try:
                observer(goal, entries)
            except Exception:
                logger.exception("Goal change observer failed for %s", goal.id)

    def _write(
        self, goal: Goal, *, actor: HistoryActor, claim_id: str | None = None, reason: str = "", noted: bool = False,
    ) -> Goal:
        saved, entries = self._files.save(goal, actor=actor, claim_id=claim_id, reason=reason, noted=noted)
        self._remember(saved)
        self._notify(saved, entries)
        return saved

    def _save_metadata(self, goal: Goal) -> Goal:
        """Save run bookkeeping; observers see it with no history entries."""
        goal.updated_at = utc_now()
        saved = self._files.save_metadata(goal)
        self._remember(saved)
        self._notify(saved, [])
        return saved

    def get(self, goal_id: str) -> Goal | None:
        if not re.fullmatch(r"[a-f0-9]{32}", goal_id):
            raise ValueError("Invalid goal ID")
        with self._lock:
            return self._files.get(goal_id)

    def list(self) -> builtins.list[Goal]:
        with self._lock:
            return self._files.list()

    def read_history(self, goal_id: str, query: str = "", before: int | None = None) -> dict:
        with self._lock:
            self._require(goal_id)
            return self._files.read_history(goal_id, query.strip(), before)

    def question(self, goal_id: str, question_id: str) -> GoalQuestion | None:
        with self._lock:
            self._require(goal_id)
            return self._files.question(goal_id, question_id)

    def history(self, conversation_id: str) -> builtins.list[Goal]:
        return [goal for goal in self.list() if goal.conversation_id == conversation_id]

    def current(self, conversation_id: str) -> Goal | None:
        with self._lock:
            goals = [goal for goal in self._open().values() if goal.conversation_id == conversation_id]
            return max(goals, key=lambda goal: goal.created_at).model_copy(deep=True) if goals else None

    def latest(self, conversation_id: str) -> Goal | None:
        return next(iter(self.history(conversation_id)), None)

    def create(self, conversation_id: str, objective: str, profile_id: str) -> Goal:
        with self._lock:
            if self.current(conversation_id.strip()) is not None:
                raise GoalConflictError("This conversation already has an unfinished goal")
            goal = Goal(conversation_id=conversation_id, objective=objective, profile_id=profile_id)
            return self._write(goal, actor="user")

    def _require(self, goal_id: str) -> Goal:
        goal = self.get(goal_id)
        if goal is None:
            raise GoalNotFoundError(f"Goal '{goal_id}' not found")
        return goal

    def _mutate(
        self, goal_id: str, change: Callable[[Goal], None], *, actor: HistoryActor,
        expected_revision: int | None = None, claim_id: str | None = None, allow_ended: bool = False,
        reason: str = "", noted: bool = False,
    ) -> Goal:
        with self._lock:
            goal = self._require(goal_id)
            if expected_revision is not None and goal.revision != expected_revision:
                raise GoalRevisionError("The goal changed since you last read it")
            if not allow_ended and goal.ended:
                raise GoalStateError("This goal has ended")
            if claim_id is not None and (goal.claim is None or goal.claim.id != claim_id):
                raise GoalConflictError("This run no longer owns the goal")
            # The app's own changes during a run belong to that run's history group.
            held = goal.claim.id if goal.claim is not None and actor == "system" else None
            change(goal)
            goal.revision += 1
            goal.updated_at = utc_now()
            tag = claim_id if claim_id is not None else held
            return self._write(goal, actor=actor, claim_id=tag, reason=reason, noted=noted)

    def update(
        self, goal_id: str, expected_revision: int, *, claim_id: str | None = None, actor: HistoryActor = "user",
        objective: str | None = None, plan: builtins.list[GoalStep] | None = None,
        step_changes: builtins.list[GoalStepChange] | None = None, summary: str | None = None,
    ) -> Goal:
        if objective is None and plan is None and step_changes is None and summary is None:
            raise ValueError("Change the plan, the summary, or both")
        if plan is not None and step_changes is not None:
            raise ValueError("Send either a whole plan or step changes")

        def change(goal: Goal) -> None:
            fields: dict[str, object] = {}
            if objective is not None:
                fields["objective"] = objective
            if plan is not None:
                fields["plan"] = plan
            if step_changes is not None:
                try:
                    fields["plan"] = apply_step_changes(goal.plan, step_changes)
                except ValidationError as exc:
                    raise ValueError(validation_message(exc)) from None
            if summary is not None:
                fields["summary"] = summary.strip()
            try:
                updated = Goal.model_validate({**goal.model_dump(), **fields})
            except ValidationError as exc:
                raise ValueError(validation_message(exc)) from None
            for name in fields:
                setattr(goal, name, getattr(updated, name))

        return self._mutate(goal_id, change, actor=actor, expected_revision=expected_revision, claim_id=claim_id)

    def pause(self, goal_id: str, *, expected_revision: int | None = None) -> Goal:
        def change(goal: Goal) -> None:
            if goal.paused:
                raise GoalStateError("This goal is already paused")
            goal.paused = True
            self._interrupt_claim(goal)
        return self._mutate(goal_id, change, actor="user", expected_revision=expected_revision)

    def resume(self, goal_id: str, *, expected_revision: int | None = None) -> Goal:
        def change(goal: Goal) -> None:
            if not goal.paused:
                raise GoalStateError("This goal is not paused")
            # Resume only turns the pause off. A wake whose time passed runs on
            # the scheduler's next check; a wait or an error stays as it is.
            goal.paused = False
        return self._mutate(goal_id, change, actor="user", expected_revision=expected_revision)

    def run(self, goal_id: str, *, expected_revision: int | None = None) -> Goal:
        """Run now from a planned wake, or retry after an error."""
        def change(goal: Goal) -> None:
            if goal.paused:
                raise GoalStateError("Resume the goal before running it")
            if goal.claim is not None:
                raise GoalStateError("The goal is already running")
            if goal.next.kind == "wake":
                goal.next = GoalWake(id=goal.next.id, at=utc_now(), reason="run_now")
            elif goal.next.kind == "error":
                goal.next = GoalWake(at=utc_now(), reason="retry")
            else:
                raise GoalStateError("This goal is waiting for you. Send a message instead.")
        return self._mutate(goal_id, change, actor="user", expected_revision=expected_revision)

    def cancel(self, goal_id: str, *, expected_revision: int | None = None) -> Goal:
        def change(goal: Goal) -> None:
            goal.next = GoalCancelled()
            goal.paused = False
            goal.claim = None
        return self._mutate(goal_id, change, actor="user", expected_revision=expected_revision)

    def reopen(self, goal_id: str) -> Goal:
        """Make an ended goal unfinished again; the user's message starts its next turn."""
        with self._lock:
            goal = self._require(goal_id)
            if not goal.ended:
                raise GoalStateError("This goal has not ended")
            if self.current(goal.conversation_id) is not None:
                raise GoalConflictError("This chat already has an unfinished goal")

            def change(item: Goal) -> None:
                item.next = GoalWait()
                item.paused = False
                item.note = ""
                item.claim = None
            return self._mutate(goal_id, change, actor="user", allow_ended=True)

    def choose(self, goal_id: str, choice: GoalChoice, *, claim_id: str, expected_revision: int) -> Goal:
        """Save the agent's next action and its note for the user."""
        picked = choice.root
        at = utc_now()
        if isinstance(picked, ScheduleChoice):
            at = utc_timestamp(picked.at)
            if datetime.fromisoformat(at) <= datetime.now(timezone.utc):
                raise ValueError(
                    f"The time must be in the future. It is now {local_time(datetime.now(timezone.utc))}. "
                    "Use continue to run again right away."
                )

        def change(goal: Goal) -> None:
            if isinstance(picked, ContinueChoice | ScheduleChoice):
                if not has_open_step(goal.plan):
                    raise GoalStateError(NO_OPEN_STEP)
                goal.next = GoalWake(at=at)
            elif isinstance(picked, CompleteChoice):
                goal.next = GoalDone(outcome=picked.outcome.strip())
            else:
                ids = picked.question_ids
                if len(set(ids)) != len(ids):
                    raise ValueError("List each question once")
                questions = {question.id: question for question in goal.questions if question.status == "open"}
                if any(item not in questions for item in ids):
                    raise GoalStateError("Wait needs existing open questions. Ask them with update_goal_questions first.")
                if any(len(questions[item].answers) > questions[item].reviewed_answer_count for item in ids):
                    raise GoalConflictError("New answers arrived. Read and evaluate them before waiting again.")
                goal.next = GoalWait(question_ids=ids)
            goal.note = picked.note
        return self._mutate(
            goal_id, change, actor="agent", expected_revision=expected_revision, claim_id=claim_id, noted=True,
        )

    def update_questions(
        self, goal_id: str, changes: builtins.list[GoalQuestionChange], expected_revision: int, *, claim_id: str,
    ) -> Goal:
        if not changes:
            raise ValueError("Send at least one question change")
        if len({change.id for change in changes}) != len(changes):
            raise ValueError("Question IDs must be unique within an update")

        def change(goal: Goal) -> None:
            for item in changes:
                previous = next((question for question in goal.questions if question.id == item.id), None)
                if previous is None:
                    previous = self._files.question(goal_id, item.id)
                    if previous is not None:
                        goal.questions.append(previous)
                if previous is None:
                    if item.question is None:
                        raise ValueError(f"New question '{item.id}' needs its text")
                    goal.questions.append(GoalQuestion(
                        id=item.id, question=item.question, status=item.status or "open", choices=item.choices or [],
                    ))
                    continue
                given = item.model_dump(exclude_unset=True, exclude={"id"})
                given = {name: value for name, value in given.items() if value is not None}
                # Only a change the user can see gives the question a new version;
                # an answer typed against the old version still sends.
                if any(getattr(previous, name) != value for name, value in given.items()):
                    for name, value in given.items():
                        setattr(previous, name, value)
                    previous.revision += 1
                    previous.updated_at = utc_now()
                previous.reviewed_answer_count = len(previous.answers)
            if goal.next.kind == "wait":
                open_ids = {question.id for question in goal.questions if question.status == "open"}
                goal.next = GoalWait(question_ids=[item for item in goal.next.question_ids if item in open_ids])

        return self._mutate(goal_id, change, actor="agent", expected_revision=expected_revision, claim_id=claim_id)

    def check_answers(self, conversation_id: str, submission: GoalAnswerSubmission) -> builtins.list[AcceptedGoalAnswer]:
        """Check replies before sending them, without saving anything.

        Every question must be open and at the version the user saw. An answer
        already saved for the same question version is dropped. Raises when
        nothing new is left to send.
        """
        with self._lock:
            accepted = self._accept(conversation_id, submission)
        if not accepted:
            raise GoalConflictError("These answers were already sent.")
        return accepted

    def save_answers(self, conversation_id: str, submission: GoalAnswerSubmission) -> builtins.list[AcceptedGoalAnswer]:
        """Save checked replies without deciding whether they answer a question.

        The same checks run again because a question can change while the
        answer waits. An answer already saved for the same question version
        is skipped, so a repeated save saves nothing and returns no answers.
        """
        with self._lock:
            accepted = self._accept(conversation_id, submission)
            if not accepted:
                return []

            def change(item: Goal) -> None:
                for answer in accepted:
                    question = next(question for question in item.questions if question.id == answer.question_id)
                    question.answers.append(GoalAnswer(**answer.model_dump(exclude={"question"})))
            self._mutate(submission.goal_id, change, actor="user")
            return accepted

    def _accept(self, conversation_id: str, submission: GoalAnswerSubmission) -> builtins.list[AcceptedGoalAnswer]:
        goal = self._require(submission.goal_id)
        if goal.conversation_id != conversation_id:
            raise GoalConflictError("These questions belong to another conversation")
        if len({answer.question_id for answer in submission.answers}) != len(submission.answers):
            raise ValueError("Submit one answer per question")
        accepted: builtins.list[AcceptedGoalAnswer] = []
        for answer in submission.answers:
            question = next((item for item in goal.questions if item.id == answer.question_id), None)
            if question is None or question.status != "open" or question.revision != answer.question_revision:
                raise GoalConflictError("A question changed. Review the current question before sending your answer.")
            if any(saved.question_revision == answer.question_revision and saved.answer == answer.answer
                   for saved in question.answers):
                continue
            accepted.append(AcceptedGoalAnswer(**answer.model_dump(), question=question.question))
        return accepted

    def due(self, now: datetime | str | None = None) -> builtins.list[Goal]:
        """Unpaused, unclaimed wakes whose time has come."""
        timestamp = datetime.fromisoformat(utc_timestamp(now) if now is not None else utc_now())
        with self._lock:
            return [goal.model_copy(deep=True) for goal in self._open().values()
                    if goal.next.kind == "wake" and not goal.paused and goal.claim is None
                    and datetime.fromisoformat(goal.next.at) <= timestamp]

    def wakes(self) -> builtins.list[Goal]:
        """Every unpaused, unclaimed goal with a planned wake, due or not."""
        with self._lock:
            return [goal.model_copy(deep=True) for goal in self._open().values()
                    if goal.next.kind == "wake" and not goal.paused and goal.claim is None]

    def claim(self, goal_id: str, wake_id: str, claim_id: str, now: datetime | str | None = None) -> Goal | None:
        """Take a due wake for a scheduled run. The wake stays in place while it runs."""
        if not claim_id:
            raise ValueError("Claim ID is required")
        timestamp = datetime.fromisoformat(utc_timestamp(now) if now is not None else utc_now())
        with self._lock:
            goal = self.get(goal_id)
            if (goal is None or goal.paused or goal.claim is not None or goal.next.kind != "wake"
                    or goal.next.id != wake_id or datetime.fromisoformat(goal.next.at) > timestamp):
                return None
            goal.claim = GoalClaim(id=claim_id, wake_id=wake_id)
            return self._save_metadata(goal)

    def claim_for_turn(self, goal_id: str, claim_id: str) -> Goal | None:
        """Own the goal for a chat turn. A chat turn never takes a wake."""
        if not claim_id:
            raise ValueError("Claim ID is required")
        with self._lock:
            goal = self.get(goal_id)
            if goal is None or goal.ended or goal.claim is not None:
                return None
            goal.claim = GoalClaim(id=claim_id)
            return self._save_metadata(goal)

    def bind_run(self, goal_id: str, claim_id: str, run_id: str) -> Goal | None:
        with self._lock:
            goal = self.get(goal_id)
            if goal is None or goal.claim is None or goal.claim.id != claim_id:
                return None
            goal.last_run_id = run_id
            return self._save_metadata(goal)

    def release(self, goal_id: str, claim_id: str) -> Goal | None:
        """Drop the claim of a run that never started."""
        with self._lock:
            goal = self.get(goal_id)
            if goal is None or goal.claim is None or goal.claim.id != claim_id:
                return None
            goal.claim = None
            return self._save_metadata(goal)

    @staticmethod
    def _interrupt_claim(goal: Goal) -> None:
        """Clear the claim; a wake its run held stays and runs again, marked interrupted."""
        claim, goal.claim = goal.claim, None
        if claim is not None and claim.wake_id is not None and goal.next.kind == "wake" and goal.next.id == claim.wake_id:
            goal.next = GoalWake(id=goal.next.id, at=goal.next.at, reason="interrupted")

    def interrupt(self, goal_id: str) -> Goal | None:
        """End a goal's run without a result, as a restart does."""
        with self._lock:
            goal = self.get(goal_id)
            if goal is None or goal.claim is None:
                return goal
            holds_wake = goal.claim.wake_id is not None and goal.next.kind == "wake" and goal.next.id == goal.claim.wake_id
            if not holds_wake:
                goal.claim = None
                return self._save_metadata(goal)
            return self._mutate(goal_id, self._interrupt_claim, actor="system")

    def recover_claims(self) -> builtins.list[Goal]:
        """After a restart, release every claim and queue interrupted wake runs again."""
        recovered = []
        with self._lock:
            for goal_id in [goal.id for goal in self._open().values() if goal.claim is not None]:
                goal = self.interrupt(goal_id)
                if goal is not None:
                    recovered.append(goal)
        return recovered

    def finish_run(
        self, goal_id: str, claim_id: str, run_id: str, status: str, error: str | None = None,
    ) -> Goal | None:
        """End a run. A wake run that chose nothing waits for the user, or shows its error."""
        with self._lock:
            goal = self.get(goal_id)
            if goal is None or goal.claim is None or goal.claim.id != claim_id:
                return None
            goal.last_run_id = run_id
            claim = goal.claim
            if claim.wake_id is None or goal.next.kind != "wake" or goal.next.id != claim.wake_id:
                goal.claim = None
                return self._save_metadata(goal)

            def change(item: Goal) -> None:
                item.last_run_id = run_id
                item.claim = None
                item.next = GoalError(message=error or "The goal run failed.") if status == "error" else GoalWait()

            if status == "stopped":
                return self._mutate(goal_id, change, actor="user", claim_id=claim.id, reason="Stopped the run.")
            return self._mutate(goal_id, change, actor="system", claim_id=claim.id)

    def delete_for_conversation(self, conversation_id: str) -> None:
        with self._lock:
            self._files.delete_for_conversation(conversation_id)
            index = self._open()
            for goal_id in [goal.id for goal in index.values() if goal.conversation_id == conversation_id]:
                del index[goal_id]
