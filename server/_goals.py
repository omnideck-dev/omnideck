"""Application-owned goal services and user controls."""

from __future__ import annotations

from aiohttp import web

from goals import GoalAnswerRecorder, GoalStore
from settings import goals_enabled
from server._agent_runtime import AGENT_RUNTIME_KEY

GOAL_STORE_KEY: web.AppKey[GoalStore] = web.AppKey("goal_store", GoalStore)


def pause_conversation_goal(app: web.Application, conversation_id: str) -> None:
    """Pause a conversation's unfinished goal before archiving its chat."""
    store = app[GOAL_STORE_KEY]
    goal = store.current(conversation_id)
    if goal is not None and not goal.paused:
        store.pause(goal.id)


def disable_goals(app: web.Application) -> None:
    """Stop goal runs when the experiment is turned off, leaving every goal as it was.

    A stopped run is treated like a restart: a wake run keeps its wake and runs
    again once Goals are back on.
    """
    store = app[GOAL_STORE_KEY]
    runtime = app[AGENT_RUNTIME_KEY]
    for goal in store.list():
        if goal.claim is None:
            continue
        store.interrupt(goal.id)
        handle = runtime.active_for_conversation(goal.conversation_id)
        if handle is not None:
            handle.stop()


def save_goal_answers_when_read(app: web.Application) -> None:
    """Save goal answers once the agent receives the chat message carrying them."""
    recorder = GoalAnswerRecorder(app[GOAL_STORE_KEY], goals_enabled)
    app[AGENT_RUNTIME_KEY].observe_events(recorder.handle_event)
