"""Application-owned goal services and user controls."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from aiohttp import web

from conversations import conversations_dir
from goals import Goal, GoalAnswerRecorder, GoalRunExtension, GoalStore, GoalWorkSource, stop_goal_runs
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
        self._subscribers: list[Callable[[ActivityMessage], bool]] = []

    def subscribe(self, send: Callable[[ActivityMessage], bool]) -> Callable[[], None]:
        def changed(goal: Goal, _entries: object) -> None:
            if self._enabled():
                send(GoalChangedMessage(type="goal_changed", conversation_id=goal.conversation_id, goal=goal))
        stop_observing = self._store.subscribe(changed)
        self._subscribers.append(send)

        def unsubscribe() -> None:
            stop_observing()
            if send in self._subscribers:
                self._subscribers.remove(send)
        return unsubscribe

    def resend_snapshot(self) -> None:
        """Send every open stream the goals, for a stream that connected while Goals was off."""
        snapshot = self.snapshot()
        if snapshot is not None:
            for send in list(self._subscribers):
                send(snapshot)

    def snapshot(self) -> ActivityMessage | None:
        if not self._enabled():
            return None
        return GoalSnapshotMessage(type="goal_snapshot", goals=self._store.latest_goals())


GOAL_FEED_KEY: web.AppKey[GoalActivityFeed] = web.AppKey("goal_feed", GoalActivityFeed)


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
    feed = GoalActivityFeed(store, goals_enabled)
    app[GOAL_FEED_KEY] = feed
    app[ACTIVITY_FEEDS_KEY].append(feed)


async def start_goals(app: web.Application) -> None:
    """Read saved goals off the event loop. A failure is logged so other scheduled work still starts."""
    try:
        await asyncio.to_thread(app[GOAL_STORE_KEY].load)
    except Exception:
        logger.exception("Could not load saved goals")


def disable_goals(app: web.Application) -> None:
    """Stop goal runs when the experiment is turned off, leaving every goal as it was."""
    stop_goal_runs(app[GOAL_STORE_KEY], app[AGENT_RUNTIME_KEY])


def enable_goals(app: web.Application) -> None:
    """Show goals on every open stream when the experiment is turned on."""
    app[GOAL_FEED_KEY].resend_snapshot()
