"""Shared helpers that drive goals through the store's real transitions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent_core.agent_capabilities import AgentCapabilities
from agent_core.context import ConversationHistory
from agent_core.control import ExecutionControl
from agent_core.turn import ExecutionContext
from goals import GoalQuestionChange, GoalRevisionTracker, GoalStep, GoalStore, make_goal_tools
from goals._models import Goal, GoalChoice


def create(store: GoalStore, conversation: str = "chat", objective: str = "Plan the family reunion") -> Goal:
    return store.create(conversation, objective, "assistant")


def future(days: int = 1) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def past(minutes: int = 5) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def with_plan(store: GoalStore, goal: Goal, *steps: GoalStep) -> Goal:
    """Give the goal a plan the way the user's editor does."""
    current = store.get(goal.id)
    plan = list(steps) or [GoalStep(id="book", title="Book the park pavilion", status="in_progress")]
    return store.update(goal.id, current.revision, plan=plan)


def claim_wake(store: GoalStore, goal: Goal, claim_id: str = "claim") -> Goal:
    """Take the goal's due wake the way the scheduler does."""
    current = store.get(goal.id)
    claimed = store.claim(goal.id, current.next.id, claim_id)
    assert claimed is not None
    return claimed


def choose(store: GoalStore, goal: Goal, claim_id: str = "claim", **fields) -> Goal:
    """Save the agent's next action inside a run that owns the goal."""
    current = store.get(goal.id)
    return store.choose(goal.id, GoalChoice.model_validate({"note": "Did some work.", **fields}),
                        claim_id=claim_id, expected_revision=current.revision)


def ask(store: GoalStore, goal: Goal, claim_id: str = "claim", question_id: str = "day",
        text: str = "Which day works for the reunion?") -> Goal:
    current = store.get(goal.id)
    return store.update_questions(goal.id, [GoalQuestionChange(id=question_id, question=text)],
                                  current.revision, claim_id=claim_id)


def chat_turn(store: GoalStore, goal: Goal, claim_id: str = "turn") -> Goal:
    claimed = store.claim_for_turn(goal.id, claim_id)
    assert claimed is not None
    return claimed


def waiting(store: GoalStore, goal: Goal, question_id: str = "day",
            text: str = "Which day works for the reunion?") -> Goal:
    """A goal that asked one question and waits for its answer."""
    chat_turn(store, goal, "setup")
    ask(store, goal, "setup", question_id, text)
    choose(store, goal, "setup", action="wait_for_input", question_ids=[question_id])
    finished = store.finish_run(goal.id, "setup", "setup-run", "success")
    assert finished is not None
    return finished


def scheduled(store: GoalStore, goal: Goal, at: str | None = None) -> Goal:
    """A goal whose agent scheduled its next run for later."""
    if not store.get(goal.id).plan:
        with_plan(store, goal)
    chat_turn(store, goal, "setup")
    choose(store, goal, "setup", action="schedule", at=at or future())
    finished = store.finish_run(goal.id, "setup", "setup-run", "success")
    assert finished is not None
    return finished


def completed(store: GoalStore, goal: Goal, outcome: str = "Booked the pavilion for June 14.") -> Goal:
    chat_turn(store, goal, "setup")
    choose(store, goal, "setup", action="complete", outcome=outcome)
    finished = store.finish_run(goal.id, "setup", "setup-run", "success")
    assert finished is not None
    return finished


def failed(store: GoalStore, goal: Goal, message: str = "Rate limit reached (429).") -> Goal:
    """A goal whose wake run failed before the agent chose anything."""
    claim_wake(store, goal, "setup")
    finished = store.finish_run(goal.id, "setup", "setup-run", "error", error=message)
    assert finished is not None
    return finished


def root_context(conversation: str = "chat", run_id: str = "run") -> ExecutionContext:
    return ExecutionContext(
        execution_id="root.agent", conversation_id=conversation, run_id=run_id,
        event_sink=ConversationHistory(conversation_id=conversation), control=ExecutionControl(),
    )


def goal_tools(store: GoalStore, goal: Goal, claim_id: str | None = "claim", *, read_only: bool = False,
               enabled=None, tracker: GoalRevisionTracker | None = None) -> dict:
    tools = make_goal_tools(store, goal.id, "root.agent", claim_id=claim_id, enabled=enabled,
                            tracker=tracker or GoalRevisionTracker(), read_only=read_only)
    return {tool.__name__: tool for tool in tools}


def bind(context: ExecutionContext):
    return context.bind("Agent", AgentCapabilities([]))


async def call(tool, **arguments) -> str:
    """Call a tool the way the agent loop does, validating JSON arguments first."""
    from agent_core.tools._helpers import _prepare_tool_arguments

    return await tool(**_prepare_tool_arguments(tool, arguments))
