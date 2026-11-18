"""Application-owned goal services and user controls."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from aiohttp import web

from conversations import conversations_dir
from goals import GoalAnswerRecorder, GoalRunExtension, GoalStore, GoalWorkSource, stop_goal_runs
from scheduling import Scheduler
from settings import goals_enabled
from server._activity_messages import ActivityMessage, GoalChangedMessage, GoalSnapshotMessage
from server._agent_runtime import AGENT_RUNTIME_KEY
from server._run_activity import ACTIVITY_FEEDS_KEY

logger = logging.getLogger(__name__)

GOAL_STORE_KEY: web.AppKey[GoalStore] = web.AppKey("goal_store", GoalStore)


class GoalActivityFeed:
    """Every goal save, and the newest goal of each chat, on the activity stream while Goals is on."""

    def __init__(self, store: GoalStore, enabled: Callable[[], bool]) -> None:
        self._store = store
        self._enabled = enabled

    def subscribe(self, send: Callable[[ActivityMessage], bool]) -> Callable[[], None]:
        def changed(goal, _entries) -> None:
            if self._enabled():
                send(GoalChangedMessage(type="goal_changed", conversation_id=goal.conversation_id, goal=goal))
        return self._store.subscribe(changed)

    def snapshot(self) -> ActivityMessage | None:
        if not self._enabled():
            return None
        return GoalSnapshotMessage(type="goal_snapshot", goals=self._store.latest_goals())


def create_goal_store(app: web.Application) -> GoalRunExtension:
    """Create the goal store and return the run extension the agent runtime needs."""
    store = GoalStore(conversations_dir())
    app[GOAL_STORE_KEY] = store
    return GoalRunExtension(store, enabled=goals_enabled)


def setup_goals(app: web.Application, scheduler: Scheduler) -> None:
    """Connect goals to the scheduler, the agent runtime's events and the activity stream."""
    store = app[GOAL_STORE_KEY]
    runtime = app[AGENT_RUNTIME_KEY]
    scheduler.register(GoalWorkSource(store, runtime, enabled=goals_enabled, on_change=scheduler.wake))
    runtime.observe_events(GoalAnswerRecorder(store, goals_enabled).handle_event)
    app[ACTIVITY_FEEDS_KEY].append(GoalActivityFeed(store, goals_enabled))


async def start_goals(app: web.Application) -> None:
    """Read saved goals off the event loop. A failure is logged so other scheduled work still starts."""
    try:
        await asyncio.to_thread(app[GOAL_STORE_KEY].load)
    except Exception:
        logger.exception("Could not load saved goals")


def disable_goals(app: web.Application) -> None:
    """Stop goal runs when the experiment is turned off, leaving every goal as it was."""
    stop_goal_runs(app[GOAL_STORE_KEY], app[AGENT_RUNTIME_KEY])
