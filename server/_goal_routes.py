"""Conversation goal assignment, editing, and user controls."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from functools import wraps

from aiohttp import web
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from agents import AgentProfile, get_agent_profile, get_default_profile
from conversations import ensure_conversation, load_conversation_profile, save_conversation_profile
from agent_runtime import AgentRunRequest, RunConflictError
from goals import (
    Goal, GoalAnswerSubmission, GoalConflictError, GoalNotFoundError, GoalStateError, GoalStep, answer_message,
)
from server._agent_run_routes import send_and_reply
from server._agent_runtime import AGENT_RUNTIME_KEY
from server._goals import GOAL_STORE_KEY
from settings import goals_enabled


class GoalAssignment(BaseModel):
    """A user's goal and the boundaries for pursuing it."""

    model_config = ConfigDict(extra="forbid")
    objective: str = Field(min_length=1, max_length=20000)
    profile_id: str | None = None


class GoalEdit(BaseModel):
    """A revision-checked edit shared by the user and the agent."""

    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    objective: str = Field(default="", min_length=1, max_length=20000)
    plan: list[GoalStep] = Field(default_factory=list, max_length=500)


class GoalControl(BaseModel):
    """A user control, optionally naming the goal the user saw and the agent picked in the chat."""

    model_config = ConfigDict(extra="forbid")
    goal_id: str | None = None
    profile_id: str | None = None


class GoalReopen(BaseModel):
    """What still needs doing, sent into the chat as the user's message."""

    model_config = ConfigDict(extra="forbid")
    goal_id: str | None = None
    text: str = Field(min_length=1, max_length=20000)
    profile_id: str | None = None

    @field_validator("text")
    @classmethod
    def text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Say what still needs doing")
        return value.strip()


class GoalAnswers(GoalAnswerSubmission):
    """Answers to a goal's questions, sent as the user's chat message."""

    profile_id: str | None = None


Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


def _user_plan(saved: list[GoalStep], edited: list[GoalStep]) -> list[GoalStep]:
    """Keep step progress as the agent saved it; the user edits only the steps' text."""
    progress = {step.id: step.status for step in saved}
    return [step.model_copy(update={"status": progress.get(step.id, "pending")}) for step in edited]


def _usable_profile(profile_id: str | None) -> AgentProfile | None:
    profile = get_agent_profile(profile_id) if profile_id else get_default_profile()
    if profile is None or not profile.enabled or not profile.model or not profile.provider:
        return None
    return profile


def _require_enabled() -> None:
    if not goals_enabled():
        raise web.HTTPForbidden(text=json.dumps({"error": "Goals are turned off."}), content_type="application/json")


def _goal_error(exc: Exception) -> web.Response | None:
    if isinstance(exc, GoalNotFoundError):
        return web.json_response({"error": str(exc.args[0]) if exc.args else "Goal not found."}, status=404)
    if isinstance(exc, (GoalConflictError, GoalStateError)):
        return web.json_response({"error": str(exc)}, status=409)
    if isinstance(exc, ValidationError):
        message = str(exc.errors()[0].get("msg", exc)).removeprefix("Value error, ")
        return web.json_response({"error": message}, status=400)
    if isinstance(exc, ValueError):
        return web.json_response({"error": str(exc)}, status=400)
    return None


def _goal_route(handler: Handler) -> Handler:
    """Check that Goals is on and map goal errors to HTTP responses."""
    @wraps(handler)
    async def wrapped(request: web.Request) -> web.StreamResponse:
        _require_enabled()
        try:
            return await handler(request)
        except Exception as exc:
            response = _goal_error(exc)
            if response is None:
                raise
            return response
    return wrapped


async def _body(request: web.Request) -> str:
    text = await request.text()
    _require_enabled()
    return text


def _conversation_id(request: web.Request) -> str:
    value = request.match_info["conversation_id"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Invalid conversation ID")
    return value


def _snapshot(request: web.Request, conversation_id: str, *, status: int = 200) -> web.Response:
    goals = request.app[GOAL_STORE_KEY].history(conversation_id)
    goal = goals[0] if goals else None
    return web.json_response({
        "goal": goal.model_dump(mode="json") if goal is not None else None,
        "earlier_goals": [item.model_dump(mode="json", include={"id", "objective", "next", "created_at"})
                          for item in goals[1:]],
    }, status=status)


@_goal_route
async def get_goal_handler(request: web.Request) -> web.Response:
    """Read a conversation's goal and its earlier goals."""
    return _snapshot(request, _conversation_id(request))


@_goal_route
async def goal_history_handler(request: web.Request) -> web.Response:
    """Load one page of a specific goal's journal, scoped to this conversation."""
    conversation_id = _conversation_id(request)
    store = request.app[GOAL_STORE_KEY]
    goal = store.get(request.query.get("goal_id", ""))
    if goal is None or goal.conversation_id != conversation_id:
        raise GoalNotFoundError("Goal not found in this conversation.")
    cursor = request.query.get("before")
    return web.json_response(store.read_history(goal.id, request.query.get("q", ""), int(cursor) if cursor else None))


@_goal_route
async def assign_goal_handler(request: web.Request) -> web.Response:
    """Assign a goal and queue its first turn in this conversation."""
    conversation_id = _conversation_id(request)
    payload = GoalAssignment.model_validate_json(await _body(request))
    store = request.app[GOAL_STORE_KEY]
    if store.current(conversation_id) is not None:
        raise GoalConflictError("This conversation already has an unfinished goal")
    profile = _usable_profile(payload.profile_id or load_conversation_profile(conversation_id))
    if profile is None:
        return web.json_response({"error": "Choose an enabled agent with a configured model."}, status=400)
    Goal(conversation_id=conversation_id, objective=payload.objective)
    ensure_conversation(conversation_id, title=payload.objective.strip(), profile_id=profile.id)
    store.create(conversation_id, payload.objective)
    return _snapshot(request, conversation_id, status=201)


@_goal_route
async def edit_goal_handler(request: web.Request) -> web.Response:
    """Revise a goal without overwriting concurrent changes."""
    conversation_id = _conversation_id(request)
    payload = GoalEdit.model_validate_json(await _body(request))
    store = request.app[GOAL_STORE_KEY]
    goal = store.current(conversation_id)
    if goal is None:
        raise GoalNotFoundError("No unfinished goal in this conversation.")
    fields = payload.model_dump(exclude_unset=True, exclude={"expected_revision"})
    store.update(
        goal.id, payload.expected_revision, actor="user",
        objective=payload.objective if "objective" in fields else None,
        plan=_user_plan(goal.plan, payload.plan) if "plan" in fields else None,
    )
    return _snapshot(request, conversation_id)


@_goal_route
async def control_goal_handler(request: web.Request) -> web.Response:
    """Pause, resume, run now, or cancel the conversation's current goal."""
    conversation_id = _conversation_id(request)
    action = request.match_info["action"]
    payload = GoalControl.model_validate_json((await _body(request)) or "{}")
    store = request.app[GOAL_STORE_KEY]
    goal = store.current(conversation_id)
    if goal is None:
        if store.latest(conversation_id) is not None:
            raise GoalStateError("This goal has ended. Reopen it first.")
        raise GoalNotFoundError("No unfinished goal in this conversation.")
    if payload.goal_id is not None and payload.goal_id != goal.id:
        raise GoalConflictError("This chat has a different goal. Refresh before changing it.")
    handle = request.app[AGENT_RUNTIME_KEY].active_for_conversation(conversation_id)
    profile = None
    if action in ("resume", "run"):
        profile = _usable_profile(payload.profile_id or load_conversation_profile(conversation_id))
        if profile is None:
            return web.json_response(
                {"error": "This chat's agent was deleted or turned off. Choose another agent in the chat."}, status=400,
            )
    if action == "resume":
        store.resume(goal.id)
    elif action == "run":
        if handle is not None:
            raise GoalStateError("Wait for the current response to finish before running the goal.")
        store.run(goal.id)
    elif action == "pause":
        store.pause(goal.id)
        if handle is not None:
            handle.stop()
    else:
        store.cancel(goal.id)
        if handle is not None:
            handle.stop()
    if profile is not None:
        save_conversation_profile(conversation_id, profile.id)
    return _snapshot(request, conversation_id)


@_goal_route
async def reopen_goal_handler(request: web.Request) -> web.Response:
    """Reopen the chat's ended goal and send what still needs doing as the user's message."""
    conversation_id = _conversation_id(request)
    payload = GoalReopen.model_validate_json(await _body(request))
    store = request.app[GOAL_STORE_KEY]
    runtime = request.app[AGENT_RUNTIME_KEY]
    goal = store.latest(conversation_id)
    if goal is None or not goal.ended:
        raise GoalStateError("This chat has no ended goal to reopen.")
    if payload.goal_id is not None and payload.goal_id != goal.id:
        raise GoalConflictError("This chat has a newer goal. Refresh before reopening.")
    if runtime.active_for_conversation(conversation_id) is not None:
        raise GoalStateError("Wait for the current response to finish before reopening.")
    store.reopen(goal.id)
    try:
        await runtime.start(AgentRunRequest(
            conversation_id=conversation_id, message=payload.text, attachments=None,
            profile_id=payload.profile_id or load_conversation_profile(conversation_id),
        ))
    except RunConflictError:
        raise GoalStateError("Another message is already being processed for this conversation.") from None
    return _snapshot(request, conversation_id)


@_goal_route
async def answer_goal_handler(request: web.Request) -> web.StreamResponse:
    """Send answers to the goal's questions as the user's message.

    The answers are saved on the goal when the agent receives the message.
    """
    conversation_id = _conversation_id(request)
    payload = GoalAnswers.model_validate_json(await _body(request))
    store = request.app[GOAL_STORE_KEY]
    submission = GoalAnswerSubmission(goal_id=payload.goal_id, answers=payload.answers)
    accepted = store.check_answers(conversation_id, submission)
    message, context, model_text = answer_message(payload.goal_id, accepted)
    return await send_and_reply(request, AgentRunRequest(
        conversation_id=conversation_id, message=message, attachments=None,
        profile_id=payload.profile_id or load_conversation_profile(conversation_id), context=context,
        model_text=model_text,
    ))


def register_goal_routes(app: web.Application) -> None:
    """Register experimental goal assignment, editing, and controls."""
    base = "/api/conversations/sessions/{conversation_id}/goal"
    app.router.add_get(base, get_goal_handler)
    app.router.add_get(base + "/history", goal_history_handler)
    app.router.add_post(base, assign_goal_handler)
    app.router.add_patch(base, edit_goal_handler)
    app.router.add_post(base + "/reopen", reopen_goal_handler)
    app.router.add_post(base + "/answers", answer_goal_handler)
    app.router.add_post(base + "/{action:pause|resume|run|cancel}", control_goal_handler)
