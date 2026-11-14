"""Goal tools bound to one root execution and its ownership claim."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

from agent_core.turn import get_execution_context

from ._context import goal_context, next_action_view
from ._models import Goal, GoalChoice, GoalQuestionChange, GoalStepChange
from ._store import GoalConflictError, GoalNotFoundError, GoalRevisionError, GoalStateError, GoalStore

GoalTool = Callable[..., Awaitable[str]]
SAVED = "Saved."


@dataclass
class GoalRevisionTracker:
    """The last goal revision the agent saw in this run. Never saved to disk."""

    seen: int | None = None


class _GoalToolError(Exception):
    """A refusal the agent can act on, returned as tool text."""


def _error_text(exc: Exception) -> str:
    if isinstance(exc, GoalRevisionError):
        return "Error: The goal changed since you last read it. Call read_goal, then try again."
    message = str(exc.args[0]) if exc.args else str(exc)
    message = message.rstrip(".")
    return f"Error: {message}."


def make_goal_tools(
    store: GoalStore, goal_id: str, execution_id: str, claim_id: str | None = None,
    enabled: Callable[[], bool] | None = None, *, tracker: GoalRevisionTracker, read_only: bool = False,
) -> list[GoalTool]:
    """Build the goal tools for one root execution.

    Reads need the root execution of the same chat while Goals are on. Writes
    also need the run's claim and a read of the goal since its last change.
    """

    def read_check() -> Goal:
        if enabled is not None and not enabled():
            raise _GoalToolError("Goals are turned off")
        context = get_execution_context()
        if context is None or context.execution_id != execution_id or context.parent_execution_id is not None:
            raise _GoalToolError("Goal tools only work in the chat's own run")
        context.control.check_stop()
        goal = store.get(goal_id)
        if goal is None or goal.conversation_id != context.conversation_id:
            raise _GoalToolError("This chat's goal no longer exists")
        return goal

    def write_check() -> tuple[Goal, str, int]:
        goal = read_check()
        context = get_execution_context()
        owner = claim_id or (context.run_id if context is not None else "")
        if goal.claim is None or goal.claim.id != owner:
            raise _GoalToolError("This run no longer owns the goal. Stop working on the goal")
        if tracker.seen is None:
            raise _GoalToolError("Read the goal with read_goal before changing it")
        return goal, owner, tracker.seen

    def guarded(body: Callable[[], str]) -> str:
        try:
            return body()
        except ValidationError:
            raise
        except (_GoalToolError, GoalConflictError, GoalStateError, GoalNotFoundError, ValueError) as exc:
            return _error_text(exc)

    async def read_goal() -> str:
        """Read the whole goal: objective, plan, questions, summary, your latest note, and what happens next.

        Read it at the start of each run and after compaction. Changes are refused until you
        have read the goal since it last changed.
        """
        def body() -> str:
            goal = read_check()
            tracker.seen = goal.revision
            held = goal.claim.wake_id if goal.claim is not None and goal.claim.id == claim_id else None
            return json.dumps(goal_context(goal, held_wake_id=held), ensure_ascii=False)
        return guarded(body)

    async def read_goal_history(query: str = "", before: int | None = None) -> str:
        """Search or browse earlier summaries, goal activity, questions and answers.

        Args:
            query: Literal text to find in the history; empty returns every kind of entry.
            before: Omit for the newest page. Pass next_before from the previous result
                to read older entries with the same query. Each page has at most 20 entries.
        """
        def body() -> str:
            read_check()
            return json.dumps(store.read_history(goal_id, query, before), ensure_ascii=False)
        return guarded(body)

    async def update_goal(plan: list[GoalStepChange] | None = None, summary: str | None = None) -> str:
        """Change plan steps, the summary, or both. This does not choose what happens next.

        Args:
            plan: Step changes by ID. Steps and fields you leave out stay as they are. A new ID
                with a title adds a step at the end, or before the step named in before.
                remove true deletes a step. Example: {"id": "book_pavilion", "status": "done"}.
            summary: The whole working summary when changing it: findings, decisions, reasons,
                answers from the user, and approaches that failed. Leave it out to keep it.
                At most 12000 characters.
        """
        def body() -> str:
            _goal, owner, seen = write_check()
            saved = store.update(
                goal_id, seen, claim_id=owner, actor="agent", step_changes=plan, summary=summary,
            )
            tracker.seen = saved.revision
            return SAVED
        return guarded(body)

    async def update_goal_questions(changes: list[GoalQuestionChange]) -> str:
        """Ask, change, resolve or withdraw questions for the user. Asking does not stop work.

        Args:
            changes: Question changes by ID. Send the ID plus only the fields that change.
                A new ID adds a question; it needs question text and starts open. Resolve a
                question once it is answered well enough, and withdraw one that no longer
                applies. Example: {"id": "day", "status": "resolved"}.
        """
        def body() -> str:
            _goal, owner, seen = write_check()
            saved = store.update_questions(goal_id, changes, seen, claim_id=owner)
            tracker.seen = saved.revision
            return SAVED
        return guarded(body)

    async def choose_next_action(
        action: Literal["continue", "schedule", "wait_for_input", "complete"], note: str,
        at: str | None = None, question_ids: list[str] | None = None, outcome: str | None = None,
    ) -> str:
        """Choose what happens after this run, with a short note for the user.

        continue and schedule need a plan step that is pending or in progress; the next run
        works on it. Asking questions does not need waiting: wait only when open questions
        block all useful work. Complete only after checking the outcome.

        Args:
            action: continue runs again right away; schedule runs again at a later time;
                wait_for_input waits for answers that block all useful work; complete ends
                the goal.
            note: One or two plain sentences for the user about what this run did. At most
                500 characters. Example: "Called the parks office. Booked 11 AM to 4 PM."
            at: Only for schedule. ISO 8601 time with a timezone offset.
            question_ids: Only for wait_for_input. IDs of the open questions that block work.
            outcome: Only for complete. What was achieved and how it was checked.
        """
        fields: dict[str, object] = {"action": action, "note": note}
        for name, value in (("at", at), ("question_ids", question_ids), ("outcome", outcome)):
            if value is not None:
                fields[name] = value
        choice = GoalChoice.model_validate(fields)

        def body() -> str:
            _goal, owner, seen = write_check()
            saved = store.choose(goal_id, choice, claim_id=owner, expected_revision=seen)
            tracker.seen = saved.revision
            return json.dumps(next_action_view(saved) or {}, ensure_ascii=False)
        return guarded(body)

    if read_only:
        return [read_goal, read_goal_history]
    return [read_goal, read_goal_history, update_goal, update_goal_questions, choose_next_action]
