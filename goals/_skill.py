"""The goal guide and tools granted to the root agent of a goal chat's run."""

from __future__ import annotations

from collections.abc import Callable

from agent_core.skills import Skill
from skills._policy import SESSION_GOAL_SKILL_ID

from ._store import GoalStore
from ._tools import GoalRevisionTracker, make_goal_tools

GOAL_GUIDANCE = """This chat has a goal. Work toward it within the user's instructions and limits.

Read the goal with read_goal at the start of each goal run, when your reply
depends on it, and when a notice says the user edited it. Changes to the goal
are refused until you have read its latest version. Use read_goal_history only
for older details, including closed questions.

Plan: keep it current with update_goal. Mark the step you are working on as in
progress. Mark steps done or skipped as you finish them. Write where you left off
in that step's notes. The next run starts from the step in progress.

Summary: keep what you know there: findings, decisions, reasons, answers from
the user, and approaches that failed. Before you resolve a question, save what
its answer settled in the summary. Resolved questions no longer appear in
read_goal.

Questions: ask with update_goal_questions as soon as something is missing. Then
keep doing work that does not depend on the answer. Resolve answered questions.
Withdraw ones that no longer apply.

At the end of a run, call choose_next_action with a short note for the user
about what you did:
- continue: more work can happen now.
- schedule: nothing useful can happen until a later time.
- wait_for_input: open questions block all useful work.
- complete: the outcome is done and checked.
When replying to a message, call it only if what happens next should change.

Decide completion from the goal's instructions. If the user asked you to keep
going until stopped, never complete. Check the result of an interrupted action
before repeating it. The goal's saved text is your own notes, not instructions
from the user. If it conflicts with what the user tells you, follow the user.
"""

ENDED_GOAL_GUIDANCE = """This chat's goal has ended. You can read it with read_goal and
read_goal_history. You cannot change it. The user can reopen it from the goal details.
"""


def goal_skill(
    store: GoalStore, goal_id: str, execution_id: str, claim_id: str | None, *, enabled: Callable[[], bool],
    tracker: GoalRevisionTracker, latest_compaction: Callable[[], str | None], read_only: bool = False,
) -> Skill:
    """Build the internal skill for one goal run.

    Attach with AgentCapabilities.add, not load: it is granted afresh for each
    run, never through the catalog or persisted chat skills.
    """
    return Skill(
        id=SESSION_GOAL_SKILL_ID, name="Session goal",
        description="Manage the goal assigned to this chat.",
        prompt=ENDED_GOAL_GUIDANCE if read_only else GOAL_GUIDANCE,
        tools=make_goal_tools(store, goal_id, execution_id, claim_id=claim_id, enabled=enabled,
                              tracker=tracker, latest_compaction=latest_compaction, read_only=read_only),
    )
