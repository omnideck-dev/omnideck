"""Dispatch explicitly requested goal wakeups into their original conversations."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from agent_runtime import AgentRunRequest, AgentRuntime, AgentRuntimeClosedError, GoalRunTrigger, RunConflictError

from ._store import GoalStore

logger = logging.getLogger(__name__)


class GoalScheduler:
    """Execute durable pending wakes without making agent disposition decisions."""

    def __init__(
        self, store: GoalStore, runtime: AgentRuntime, *,
        enabled: Callable[[], bool] | None = None, poll_interval: float = 1.0,
    ) -> None:
        self._store = store
        self._runtime = runtime
        self._enabled = enabled if enabled is not None else lambda: True
        self._poll_interval = poll_interval
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()
        self._tick_lock = asyncio.Lock()

    async def start(self) -> None:
        """Recover interrupted claims once and begin checking pending wakeups."""
        if self._task is not None:
            return
        self._store.recover_claims()
        self._stopping.clear()
        self._task = asyncio.create_task(self._poll(), name="goal-scheduler")

    async def stop(self) -> None:
        """Stop admitting goal work while leaving accepted runs runtime-owned."""
        self._stopping.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def tick(self, now: datetime | str | None = None) -> None:
        """Claim each due wake once, preserving wakes whose conversation is busy."""
        async with self._tick_lock:
            if self._stopping.is_set() or not self._enabled():
                return
            for goal in self._store.due(now):
                if not self._enabled() or self._stopping.is_set():
                    return
                if self._runtime.active_for_conversation(goal.conversation_id) is not None:
                    continue
                if goal.wake_id is None:
                    continue
                claim_id = f"goal_claim_{uuid4().hex}"
                claimed = self._store.claim(goal.id, goal.wake_id, claim_id, now=now)
                if claimed is None:
                    continue
                trigger = GoalRunTrigger(
                    goal_id=claimed.id,
                    wake_id=goal.wake_id,
                    claim_id=claim_id,
                    reason=goal.wake_reason or "Continue the assigned goal",
                    next_action=goal.next_action,
                )
                try:
                    await self._runtime.start(AgentRunRequest(
                        conversation_id=goal.conversation_id,
                        message=trigger.next_action,
                        attachments=None,
                        profile_id=goal.profile_id,
                        goal_trigger=trigger,
                    ))
                except (RunConflictError, AgentRuntimeClosedError):
                    self._store.requeue_claim(goal.id, claim_id)
                except Exception as exc:
                    logger.exception("Could not admit goal wake %s", goal.wake_id)
                    self._store.finish_run(goal.id, claim_id, claim_id, "error", error=str(exc))

    async def _poll(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.tick()
            except Exception:
                logger.exception("Goal scheduler tick failed")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self._poll_interval)
            except TimeoutError:
                pass
