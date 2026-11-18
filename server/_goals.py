"""Application-owned goal services and user controls."""

from __future__ import annotations

from aiohttp import web

from goals import GoalAnswerRecorder, GoalStore, stop_goal_runs
from settings import goals_enabled
from server._agent_runtime import AGENT_RUNTIME_KEY

GOAL_STORE_KEY: web.AppKey[GoalStore] = web.AppKey("goal_store", GoalStore)


def disable_goals(app: web.Application) -> None:
    """Stop goal runs when the experiment is turned off, leaving every goal as it was."""
    stop_goal_runs(app[GOAL_STORE_KEY], app[AGENT_RUNTIME_KEY])


def save_goal_answers_when_read(app: web.Application) -> None:
    """Save goal answers once the agent receives the chat message carrying them."""
    recorder = GoalAnswerRecorder(app[GOAL_STORE_KEY], goals_enabled)
    app[AGENT_RUNTIME_KEY].observe_events(recorder.handle_event)
