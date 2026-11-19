"""A goal's part in every run of its chat: tools, opening events and the outcome divider."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from agent_core.control import StopRequestedError
from agent_core.events import AgentEvent, GoalEventPayload, GoalTransitionData, GoalWakeupData
from agent_core.turn import ExecutionResult
from agent_runtime import AgentRunRequest, AgentRuntime, RunAdditions, RunSession

from ._models import GoalNext, WakeReason
from ._skill import goal_skill
from ._store import GoalStore
from ._tools import GoalRevisionTracker

logger = logging.getLogger(__name__)

EDITED_TEXT = "The user edited the goal. Read it before relying on your earlier copy."
_WAKE_REASON_TEXT: dict[str, str] = {
    "planned": "",
    "run_now": "The user asked to run the goal now.",
    "retry": "The last run failed. The user asked to try again.",
    "interrupted": "The last run was interrupted. Check what it already did before repeating actions.",
}


@dataclass(frozen=True, slots=True)
class GoalRunTrigger:
    """A goal run the scheduler started for a due wake."""

    goal_id: str
    wake_id: str
    claim_id: str
    reason: WakeReason
    step: str


@dataclass(frozen=True, slots=True)
class _OwnedRun:
    goal_id: str
    claim_id: str
    before: GoalNext


def wakeup_text(reason: WakeReason) -> str:
    lines = ["A goal run started. Read the goal."]
    if _WAKE_REASON_TEXT[reason]:
        lines.append(_WAKE_REASON_TEXT[reason])
    return "\n".join(lines)


def _wakeup_event(trigger: GoalRunTrigger) -> AgentEvent:
    return AgentEvent(
        payload=GoalEventPayload(type="goal", goal_id=trigger.goal_id, data=GoalWakeupData(
            kind="wakeup", wake_id=trigger.wake_id, reason=trigger.reason, step=trigger.step,
        )),
        model_text=wakeup_text(trigger.reason),
    )


def _edited_event(goal_id: str) -> AgentEvent:
    return AgentEvent(
        payload=GoalEventPayload(type="goal", goal_id=goal_id, data=GoalTransitionData(kind="edited")),
        model_text=EDITED_TEXT,
    )


def outcome_divider(goal_id: str, before: GoalNext, after: GoalNext) -> AgentEvent | None:
    """The divider for what a run changed about what happens next, if anything."""
    data = None
    if after.kind == "wake":
        future = datetime.fromisoformat(after.at) > datetime.now(timezone.utc)
        if future and after != before:
            data = GoalTransitionData(kind="scheduled", resume_at=after.at)
    elif after.kind == "wait":
        gained = set(after.question_ids) - set(before.question_ids) if before.kind == "wait" else True
        if gained:
            data = GoalTransitionData(kind="waiting", question_count=len(after.question_ids))
    elif after.kind == "error" and before.kind != "error":
        data = GoalTransitionData(kind="error")
    elif after.kind == "done" and before.kind != "done":
        data = GoalTransitionData(kind="completed")
    if data is None:
        return None
    return AgentEvent(payload=GoalEventPayload(type="goal", goal_id=goal_id, data=data))


def _latest_compaction(run: RunSession) -> str | None:
    history = run.history
    if history is None:
        return None
    return next((event["id"] for event in reversed(history.scoped_events) if event["type"] == "compaction"), None)


def _previous_run_start(run: RunSession) -> str | None:
    history = run.history
    if history is None:
        return None
    return next((event["timestamp"] for event in reversed(history.scoped_events)
                 if event["type"] == "agent_started"), None)


class GoalRunExtension:
    """Give a goal chat's root agent its goal, and close goal runs."""

    def __init__(self, store: GoalStore, *, enabled: Callable[[], bool]) -> None:
        self._store = store
        self._enabled = enabled
        self._owned: dict[str, _OwnedRun] = {}

    async def before_run(self, request: AgentRunRequest, run: RunSession) -> RunAdditions | None:
        trigger = request.trigger if isinstance(request.trigger, GoalRunTrigger) else None
        if not self._enabled():
            if trigger is not None:
                raise StopRequestedError()
            return None
        if trigger is not None:
            goal = self._store.get(trigger.goal_id)
            if (goal is None or goal.conversation_id != run.conversation_id
                    or goal.claim is None or goal.claim.id != trigger.claim_id):
                raise StopRequestedError()
            claim_id: str | None = trigger.claim_id
        else:
            goal = self._store.latest(run.conversation_id)
            if goal is None:
                return None
            claim_id = None
            if not goal.ended:
                claimed = self._store.claim_for_turn(goal.id, run.run_id)
                if claimed is None:
                    return None
                goal, claim_id = claimed, run.run_id
        opening: list[AgentEvent] = []
        if claim_id is not None:
            self._store.bind_run(goal.id, claim_id, run.run_id)
            self._owned[run.run_id] = _OwnedRun(goal.id, claim_id, goal.next)
            since = _previous_run_start(run)
            if since is not None and self._store.edited_by_user_since(goal.id, since):
                opening.append(_edited_event(goal.id))
        if trigger is not None:
            opening.append(_wakeup_event(trigger))
        skill = goal_skill(
            self._store, goal.id, run.root_context.execution_id, claim_id, enabled=self._enabled,
            tracker=GoalRevisionTracker(), latest_compaction=lambda: _latest_compaction(run),
            read_only=claim_id is None,
        )
        return RunAdditions(skills=(skill,), opening_events=tuple(opening))

    def after_run(
        self, request: AgentRunRequest, run: RunSession, result: ExecutionResult, *, shutting_down: bool,
    ) -> Sequence[AgentEvent]:
        owned = self._owned.pop(run.run_id, None)
        if owned is None or shutting_down:
            return []
        goal = self._store.finish_run(owned.goal_id, owned.claim_id, run.run_id, result.status, error=result.error)
        if goal is None:
            goal = self._store.get(owned.goal_id)
        if goal is None:
            return []
        divider = outcome_divider(goal.id, owned.before, goal.next)
        return [divider] if divider is not None else []


def stop_goal_runs(store: GoalStore, runtime: AgentRuntime) -> None:
    """Stop every goal run and goal chat turn, leaving every goal as it was.

    A stopped wake run keeps its wake and runs again, marked interrupted.
    """
    for goal in store.recover_claims():
        handle = runtime.active_for_conversation(goal.conversation_id)
        if handle is not None:
            handle.stop()
