"""Translate durable goal wakes into shared scheduler work."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from functools import partial
from uuid import uuid4

from agent_runtime import AgentRunRequest, AgentRuntime, AgentRuntimeClosedError, GoalRunTrigger, RunConflictError
from scheduling import ScheduledWork
from ._models import next_step
from ._store import GoalStore

logger = logging.getLogger(__name__)


class GoalWorkSource:
    name = "goals"

    def __init__(
        self, store: GoalStore, runtime: AgentRuntime, *, enabled: Callable[[], bool],
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._store = store
        self._runtime = runtime
        self._enabled = enabled
        if on_change is not None:
            # Any saved change can make a wake due, so check again without waiting for the next poll.
            store.subscribe(lambda _goal, _entries: on_change())

    @property
    def enabled(self) -> bool:
        return self._enabled()

    def recover(self) -> None:
        self._store.recover_claims()

    def pending(self, now: datetime) -> list[ScheduledWork]:
        return [ScheduledWork(
            id=goal.next.id, target=goal.conversation_id,
            due_at=datetime.fromisoformat(goal.next.at), labels={"goal": goal.id},
            dispatch=partial(self._dispatch, goal.id, goal.next.id, now),
        ) for goal in self._store.wakes() if goal.next.kind == "wake"]

    async def _dispatch(self, goal_id: str, wake_id: str, now: datetime) -> asyncio.Future | None:
        if not self.enabled:
            return None
        goal = self._store.get(goal_id)
        if goal is None or self._runtime.active_for_conversation(goal.conversation_id) is not None:
            return None
        claim_id = f"goal_claim_{uuid4().hex}"
        claimed = self._store.claim(goal.id, wake_id, claim_id, now=now)
        if claimed is None or claimed.next.kind != "wake":
            return None
        step = next_step(claimed.plan)
        trigger = GoalRunTrigger(
            goal_id=claimed.id, wake_id=wake_id, claim_id=claim_id, reason=claimed.next.reason,
            step=step.title if step is not None else "",
        )
        try:
            handle = await self._runtime.start(AgentRunRequest(
                conversation_id=claimed.conversation_id, message=trigger.step or "Continue the goal.",
                attachments=None, profile_id=claimed.profile_id, goal_trigger=trigger,
            ))
        except (RunConflictError, AgentRuntimeClosedError):
            self._store.release(goal.id, claim_id)
            return None
        except Exception as exc:
            logger.exception("Could not admit goal wake %s", wake_id)
            self._store.finish_run(goal.id, claim_id, claim_id, "error", error=str(exc))
            return None
        # RunHandle.wait is shielded: scheduler shutdown stops this observer,
        # then AgentRuntime.close preserves interrupted claims for recovery.
        return asyncio.create_task(handle.wait(), name=f"scheduled-goal-{goal.id}")
