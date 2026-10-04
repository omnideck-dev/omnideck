"""Goal tools bound to one root execution and its durable ownership claim."""

from collections.abc import Awaitable, Callable

from agent_core.turn import get_execution_context

from ._models import Goal, GoalStep, TERMINAL_STATUSES, utc_now
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

    async def read_goal() -> str:
        """Read the assigned goal, current plan revision, progress, and scheduled wake."""
        goal, _owner = require_owner()
        return goal.model_dump_json()

    async def update_goal_plan(plan: list[GoalStep], expected_revision: int) -> str:
        """Replace the goal checklist while preserving IDs for existing steps.

        Args:
            plan: Complete ordered checklist. Each item needs a stable id and title;
                status is pending, in_progress, done, blocked, or skipped. Optional
                notes describe evidence or blockers; depends_on lists other step IDs.
            expected_revision: Revision returned by the latest goal read or update.
                Read again and reconcile changes if the revision is stale.
        """
        _goal, owner = require_owner()
        return store.update(goal_id, expected_revision, claim_id=owner, plan=plan).model_dump_json()

    async def record_goal_progress(summary: str, next_action: str) -> str:
        """Record durable progress and the next intended action without scheduling a turn.

        Args:
            summary: Concrete work completed, evidence obtained, or a blocker discovered.
            next_action: What should happen next; use an empty string when none remains.
        """
        _goal, owner = require_owner()
        return store.record_progress(goal_id, summary, next_action, claim_id=owner).model_dump_json()

    async def continue_goal(reason: str, next_action: str) -> str:
        """Explicitly queue another goal turn after this execution ends.

        Args:
            reason: Why an additional turn is needed and can make progress now.
            next_action: Concrete work for the next turn, including any checks before acting.
        """
        _goal, owner = require_owner()
        return store.schedule(goal_id, utc_now(), reason, next_action, claim_id=owner, immediate=True).model_dump_json()

    async def schedule_goal_resume(resume_at: str, reason: str, next_action: str) -> str:
        """Schedule one future goal turn after completing the actions possible now.

        Args:
            resume_at: Future ISO 8601 timestamp with an explicit timezone offset.
            reason: Why waiting until that time is useful or necessary.
            next_action: What the resumed agent should inspect or do next.
        """
        _goal, owner = require_owner()
        return store.schedule(goal_id, resume_at, reason, next_action, claim_id=owner).model_dump_json()

    async def wait_for_goal_input(reason: str) -> str:
        """Stop automatic continuation until the user supplies needed input.

        Args:
            reason: The specific missing information or decision needed from the user.
        """
        _goal, owner = require_owner()
        return store.wait_for_input(goal_id, reason, claim_id=owner).model_dump_json()

    async def complete_goal(outcome: str) -> str:
        """Mark the goal complete only after its requested outcome has been achieved.

        Args:
            outcome: The achieved result and evidence that the success criteria are met.
        """
        _goal, owner = require_owner()
        return store.complete(goal_id, outcome, claim_id=owner).model_dump_json()

    return [read_goal, update_goal_plan, record_goal_progress, continue_goal, schedule_goal_resume,
            wait_for_goal_input, complete_goal]
