"""Goal tools bound to one root execution and its durable ownership claim."""

import json
from collections.abc import Awaitable, Callable

from agent_core.turn import get_execution_context

from ._context import goal_context
from ._models import Goal, GoalQuestionChange, GoalStep, TERMINAL_STATUSES, utc_now
from ._store import GoalConflictError, GoalNotFoundError, GoalStateError, GoalStore

GoalTool = Callable[..., Awaitable[str]]


def make_goal_tools(
    store: GoalStore, goal_id: str, execution_id: str, claim_id: str | None = None,
    enabled: Callable[[], bool] | None = None,
) -> list[GoalTool]:
    """Build tools scoped to the root execution that currently owns a goal."""

    def require_owner() -> tuple[Goal, str]:
        if enabled is not None and not enabled():
            raise GoalStateError("Experimental goals are disabled")
        context = get_execution_context()
        if (context is None or context.execution_id != execution_id or context.parent_execution_id is not None):
            raise GoalConflictError("Goal tools are only available to their owning root execution")
        context.control.check_stop()
        goal = store.get(goal_id)
        if goal is None:
            raise GoalNotFoundError("The assigned goal no longer exists")
        owner = claim_id or context.run_id
        if goal.conversation_id != context.conversation_id or goal.claimed_run_id != owner:
            raise GoalConflictError("This execution no longer owns the assigned goal")
        if goal.status == "paused" or goal.status in TERMINAL_STATUSES:
            raise GoalStateError("The assigned goal is paused or has ended")
        return goal, owner

    def result(goal: Goal) -> str:
        return json.dumps(goal_context(goal))

    async def read_goal() -> str:
        """Read the compact goal state: summary, working plan, open questions and recent progress."""
        goal, _owner = require_owner()
        return result(goal)

    async def read_goal_history(query: str = "", before: int | None = None) -> str:
        """Search or browse preserved progress, decisions, plan revisions, questions and answers.

        Args:
            query: Literal text to find in the journal; empty returns all types of entries.
            before: Omit for the newest page. Pass next_before from the previous result
                to read older entries with the same query. Each page contains at most 20 entries.
        """
        require_owner()
        return json.dumps(store.read_history(goal_id, query, before))

    async def update_goal_summary(summary: str, expected_revision: int) -> str:
        """Replace the compact handoff summary without deleting underlying history.

        Args:
            summary: Current outcomes, decisions and reasons, failed approaches to avoid,
                remaining work and relevant evidence references. Keep concise; at most 12000 characters.
            expected_revision: Revision from the latest goal read or update. Re-read if stale.
        """
        _goal, owner = require_owner()
        return result(store.update(goal_id, expected_revision, claim_id=owner,
                                   reason="Goal summary updated", summary=summary))

    async def update_goal_questions(
        changes: list[GoalQuestionChange], known_facts: str, expected_revision: int,
    ) -> str:
        """Ask or manage questions without stopping work; retain previous versions and answers.

        Args:
            changes: Question updates with stable IDs, full question text, status, and optional
                choices. Omitted questions are unchanged. Resolve sufficient answers;
                withdraw questions that no longer apply. Updating acknowledges received answers.
            known_facts: Complete concise CURRENT facts learned from answers, including useful
                earlier facts. Replaces the summary; exclude superseded values and change history.
                Changes may be empty when only the facts need updating.
            expected_revision: Revision from the latest goal read or successful update.
                Read again and reconcile if stale, including newly submitted answers.
        """
        _goal, owner = require_owner()
        goal = store.update_questions(goal_id, changes, known_facts, expected_revision, claim_id=owner)
        snapshot = goal_context(goal)
        snapshot["question_updates"] = []
        for item in changes:
            question = store.question(goal_id, item.id)
            assert question is not None  # Persisted by the transaction above.
            snapshot["question_updates"].append(question.model_dump(mode="json", exclude={"answers"}))
        return json.dumps(snapshot)

    async def update_goal_plan(plan: list[GoalStep], reason: str, expected_revision: int) -> str:
        """Replace the goal checklist while preserving IDs for existing steps.

        Args:
            plan: Complete ordered checklist. Each item needs a stable id and title;
                status is pending, in_progress, done, blocked, or skipped. Optional
                notes describe evidence or blockers; depends_on lists other step IDs.
            reason: Why the approach or steps changed, including evidence or decisions.
            expected_revision: Revision returned by the latest goal read or update.
                Read again and reconcile changes if the revision is stale.
        """
        _goal, owner = require_owner()
        if not reason.strip():
            raise ValueError("Explain why the plan changed")
        return result(store.update(goal_id, expected_revision, claim_id=owner, reason=reason.strip(), plan=plan))

    async def record_goal_progress(summary: str, next_action: str) -> str:
        """Record durable progress and the next intended action without scheduling a turn.

        Args:
            summary: Concrete work completed, evidence obtained, or a blocker discovered.
            next_action: What should happen next; use an empty string when none remains.
        """
        _goal, owner = require_owner()
        return result(store.record_progress(goal_id, summary, next_action, claim_id=owner))

    async def continue_goal(reason: str, next_action: str) -> str:
        """Explicitly queue another goal turn after this execution ends.

        Args:
            reason: Why an additional turn is needed and can make progress now.
            next_action: Concrete work for the next turn, including any checks before acting.
        """
        _goal, owner = require_owner()
        return result(store.schedule(goal_id, utc_now(), reason, next_action, claim_id=owner, immediate=True))

    async def schedule_goal_resume(resume_at: str, reason: str, next_action: str) -> str:
        """Schedule one future goal turn after completing the actions possible now.

        Args:
            resume_at: Future ISO 8601 timestamp with an explicit timezone offset.
            reason: Why waiting until that time is useful or necessary.
            next_action: What the resumed agent should inspect or do next.
        """
        _goal, owner = require_owner()
        return result(store.schedule(goal_id, resume_at, reason, next_action, claim_id=owner))

    async def wait_for_goal_input(question_ids: list[str]) -> str:
        """Stop automatic continuation only when open questions block all useful work.

        Args:
            question_ids: Nonempty IDs of existing open questions blocking further work.
                Ask or revise them with update_goal_questions first. Review new answers before waiting.
        """
        _goal, owner = require_owner()
        return result(store.wait_for_input(goal_id, question_ids, claim_id=owner))

    async def complete_goal(outcome: str) -> str:
        """Mark the goal complete only after its requested outcome has been achieved.

        Args:
            outcome: The achieved result and evidence that the success criteria are met.
        """
        _goal, owner = require_owner()
        return result(store.complete(goal_id, outcome, claim_id=owner))

    return [read_goal, read_goal_history, update_goal_summary, update_goal_questions, update_goal_plan, record_goal_progress, continue_goal, schedule_goal_resume,
            wait_for_goal_input, complete_goal]
