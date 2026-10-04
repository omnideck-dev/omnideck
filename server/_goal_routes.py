"""Conversation goal assignment, editing, and user controls."""

from __future__ import annotations

import re

from aiohttp import web
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agents import get_agent_profile, get_default_profile
from conversations import conversation_exists, ensure_conversation, load_conversation_profile
from goals import Goal, GoalConflictError, GoalKind, GoalStateError, GoalStep
from server._agent_runtime import AGENT_RUNTIME_KEY
from server._goals import GOAL_STORE_KEY
from settings import goals_enabled


class GoalAssignment(BaseModel):
    """A user's goal and the boundaries for pursuing it."""

    model_config = ConfigDict(extra="forbid")
    objective: str = Field(min_length=1, max_length=20000)
    kind: GoalKind = "finite"
    constraints: str = Field(default="", max_length=20000)
    success_criteria: list[str] = Field(default_factory=list, max_length=100)
    profile_id: str | None = None


class GoalEdit(BaseModel):
    """A revision-checked edit shared by the user and the agent."""

    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    objective: str = Field(default="", min_length=1, max_length=20000)
    kind: GoalKind = "finite"
    constraints: str = Field(default="", max_length=20000)
    success_criteria: list[str] = Field(default_factory=list, max_length=100)
    plan: list[GoalStep] = Field(default_factory=list, max_length=500)


class GoalControl(BaseModel):
    """An optional revision precondition for a user control."""

    model_config = ConfigDict(extra="forbid")
    expected_revision: int | None = Field(default=None, ge=1)
    goal_id: str | None = None


class GoalView(Goal):
    """A goal with the live activity of its owning conversation."""

    running: bool = False
    run_id: str | None = None


def _require_enabled() -> None:
    if not goals_enabled():
        raise web.HTTPNotFound(text="Goals are disabled. Enable Goals in Settings > System > Experimental.")


def _conversation_id(request: web.Request) -> str:
    value = request.match_info["conversation_id"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Invalid conversation ID")
    return value


def _view(request: web.Request, goal: Goal) -> GoalView:
    handle = request.app[AGENT_RUNTIME_KEY].active_for_conversation(goal.conversation_id)
    running = handle is not None and handle.run_id == goal.last_run_id
    return GoalView(
        **goal.model_dump(),
        running=running,
        run_id=handle.run_id if handle is not None and running else None,
    )


def _snapshot(request: web.Request, conversation_id: str, *, status: int = 200) -> web.Response:
    store = request.app[GOAL_STORE_KEY]
    goal = store.latest(conversation_id)
    view = _view(request, goal) if goal is not None else None
    return web.json_response({
        "goal": view.model_dump(mode="json") if view else None,
        "history": [item.model_dump(mode="json") for item in store.history(conversation_id)],
        "running": view.running if view else False,
    }, status=status)


async def list_goals_handler(request: web.Request) -> web.Response:
    """List the latest goal for each visible conversation."""
    _require_enabled()
    seen: set[str] = set()
    goals: list[GoalView] = []
    for goal in request.app[GOAL_STORE_KEY].list():
        if goal.conversation_id in seen or not conversation_exists(goal.conversation_id):
            continue
        seen.add(goal.conversation_id)
        goals.append(_view(request, goal))
    return web.json_response({"goals": [goal.model_dump(mode="json") for goal in goals]})


async def get_goal_handler(request: web.Request) -> web.Response:
    """Read a conversation's goal, history, and current execution status."""
    _require_enabled()
    try:
        return _snapshot(request, _conversation_id(request))
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)


async def assign_goal_handler(request: web.Request) -> web.Response:
    """Assign a goal and queue its first turn in this conversation."""
    _require_enabled()
    try:
        conversation_id = _conversation_id(request)
        payload = GoalAssignment.model_validate_json(await request.text())
        _require_enabled()
        if request.app[GOAL_STORE_KEY].current(conversation_id) is not None:
            raise GoalConflictError("This conversation already has an unfinished goal")
        profile_id = payload.profile_id or load_conversation_profile(conversation_id)
        profile = get_agent_profile(profile_id) if profile_id else get_default_profile()
        if profile is None or not profile.enabled or not profile.model or not profile.provider:
            return web.json_response({"error": "Choose an enabled agent with a configured model."}, status=400)
        # Validate the goal before creating its conversation or its pending wake.
        Goal(
            conversation_id=conversation_id, objective=payload.objective, profile_id=profile.id,
            kind=payload.kind, constraints=payload.constraints, success_criteria=payload.success_criteria,
        )
        ensure_conversation(conversation_id, title=payload.objective.strip(), profile_id=profile.id)
        request.app[GOAL_STORE_KEY].create(
            conversation_id, payload.objective, profile.id, kind=payload.kind,
            constraints=payload.constraints, success_criteria=payload.success_criteria,
        )
    except GoalConflictError as exc:
        return web.json_response({"error": str(exc)}, status=409)
    except (ValueError, RuntimeError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return _snapshot(request, conversation_id, status=201)


async def edit_goal_handler(request: web.Request) -> web.Response:
    """Revise a goal without overwriting concurrent changes."""
    _require_enabled()
    try:
        conversation_id = _conversation_id(request)
        payload = GoalEdit.model_validate_json(await request.text())
        _require_enabled()
        store = request.app[GOAL_STORE_KEY]
        goal = store.current(conversation_id)
        if goal is None:
            return web.json_response({"error": "No unfinished goal in this conversation."}, status=404)
        store.update(
            goal.id, payload.expected_revision,
            **payload.model_dump(exclude_unset=True, exclude={"expected_revision"}),
        )
    except (GoalConflictError, GoalStateError) as exc:
        return web.json_response({"error": str(exc)}, status=409)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return _snapshot(request, conversation_id)


async def control_goal_handler(request: web.Request) -> web.Response:
    """Pause, resume now, or cancel the conversation's current goal."""
    _require_enabled()
    try:
        conversation_id = _conversation_id(request)
        action = request.match_info["action"]
        payload = GoalControl.model_validate_json((await request.text()) or "{}")
        _require_enabled()
        store = request.app[GOAL_STORE_KEY]
        goal = store.current(conversation_id)
        if goal is None:
            return web.json_response({"error": "No unfinished goal in this conversation."}, status=404)
        if payload.goal_id is not None and payload.goal_id != goal.id:
            return web.json_response({"error": "This chat has a different goal. Refresh before changing it."}, status=409)
        if not conversation_exists(conversation_id):
            return web.json_response({"error": "Restore this conversation before resuming its goal."}, status=409)
        handle = request.app[AGENT_RUNTIME_KEY].active_for_conversation(conversation_id)
        if action == "resume":
            if handle is not None:
                return web.json_response({"error": "Wait for the current response to stop before resuming."}, status=409)
            store.resume(goal.id, expected_revision=payload.expected_revision)
        elif action == "pause":
            store.pause(goal.id, expected_revision=payload.expected_revision)
            if handle is not None:
                handle.stop()
        elif action == "cancel":
            store.cancel(goal.id, expected_revision=payload.expected_revision)
            if handle is not None:
                handle.stop()
        else:
            raise web.HTTPNotFound()
    except (GoalConflictError, GoalStateError) as exc:
        return web.json_response({"error": str(exc)}, status=409)
    except (ValueError, ValidationError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return _snapshot(request, conversation_id)


def register_goal_routes(app: web.Application) -> None:
    """Register experimental goal assignment, editing, and controls."""
    base = "/api/conversations/sessions/{conversation_id}/goal"
    app.router.add_get("/api/goals", list_goals_handler)
    app.router.add_get(base, get_goal_handler)
    app.router.add_post(base, assign_goal_handler)
    app.router.add_patch(base, edit_goal_handler)
    app.router.add_post(base + "/{action:pause|resume|cancel}", control_goal_handler)
