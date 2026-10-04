"""Application-owned goal services and user controls."""

from __future__ import annotations

from aiohttp import web

from goals import GoalStore
from goals._scheduler import GoalScheduler
from server._agent_runtime import AGENT_RUNTIME_KEY

GOAL_STORE_KEY: web.AppKey[GoalStore] = web.AppKey("goal_store", GoalStore)
GOAL_SCHEDULER_KEY: web.AppKey[GoalScheduler] = web.AppKey("goal_scheduler", GoalScheduler)


def pause_conversation_goal(app: web.Application, conversation_id: str) -> None:
    """Disarm a conversation's unfinished goal before stopping or archiving."""
    store = app[GOAL_STORE_KEY]
    goal = store.current(conversation_id)
    if goal is not None and goal.status != "paused":
        store.pause(goal.id)


def disable_goals(app: web.Application) -> None:
    """Pause saved goals and stop their active runs when the experiment is disabled."""
    store = app[GOAL_STORE_KEY]
    runtime = app[AGENT_RUNTIME_KEY]
    for goal in store.list():
        if goal.status in {"completed", "cancelled"}:
            continue
        if goal.status != "paused":
            store.pause(goal.id)
        handle = runtime.active_for_conversation(goal.conversation_id)
        if handle is not None:
            handle.stop()
