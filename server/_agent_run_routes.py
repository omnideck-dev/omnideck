"""HTTP channel adapter for starting, following, and controlling agent runs.

The legacy ``/api/chat`` URLs remain stable for the browser, but this module
translates their chat-shaped wire contract into the channel-neutral
``agent_runtime`` vocabulary.

Endpoints:
    POST /api/chat                              — start and follow an agent run
    GET  /api/chat/runs/{run_id}/events         — replay and follow an active run
    POST /api/chat/stop                         — request cooperative run stop
    POST /api/nudge                             — queue a nudge for an active agent
    GET  /api/nudges                            — list an agent's pending nudges
    DELETE /api/nudges/{nudge_id}               — delete one pending nudge
"""

from __future__ import annotations

import json
import logging
from contextlib import suppress
from typing import TYPE_CHECKING

from aiohttp import web
from pydantic import BaseModel, ValidationError

from agent_runtime import (
    ActiveRunConflictError,
    ActiveRunManagerClosedError,
    AgentRunRequest,
    InvalidRunCursorError,
    RunAttachment,
    UnknownActiveRunError,
)
from sdk.turn import delete_nudge, is_turn_active, list_nudges, queue_nudge
from server._agent_runtime import ACTIVE_RUN_MANAGER_KEY

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import AsyncGenerator

    from aiohttp.web_request import Request
    from aiohttp.web_response import Response, StreamResponse

    from agent_runtime import SequencedEvent

logger = logging.getLogger(__name__)


class Attachment(BaseModel):
    """One attachment in the legacy chat request contract."""

    base64: str
    content_type: str
    filename: str | None = None


class ChatRequest(BaseModel):
    """Legacy chat-shaped request translated into an ``AgentRunRequest``."""

    message: str
    data: list[Attachment] | None = None
    profile_id: str | None = None
    conversation_id: str | None = None


class NudgeRequest(BaseModel):
    """Request model for nudging a running agent."""

    message: str
    conversation_id: str
    agent_id: str


async def stream_events(
    request: Request,
    records: AsyncGenerator[SequencedEvent, None],
) -> StreamResponse:
    """Stream replayed followed by live agent-run records as JSONL."""
    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Transfer-Encoding": "chunked",
        },
    )
    await response.prepare(request)

    try:
        async for record in records:
            data_out = record.event.model_dump(
                mode="json",
                exclude_none=True,
                exclude_defaults=True,
            )
            data_out["run_id"] = record.run_id
            data_out["seq"] = record.seq
            await response.write((json.dumps(data_out) + "\n").encode("utf-8"))
    except ConnectionResetError:
        logger.debug("Client disconnected during event stream")
    except Exception:  # pragma: no cover - defensive logging
        logger.exception("Error while streaming events")
    finally:
        # Closing a subscription removes only its waiter. The manager-owned
        # runner task remains alive and continues retaining records.
        await records.aclose()
        with suppress(ConnectionResetError):
            await response.write_eof()
    return response


async def chat_handler(request: Request) -> StreamResponse:
    """Adapt the legacy chat endpoint to the channel-neutral agent runtime."""
    raw_body = await request.text()
    try:
        payload = ChatRequest.model_validate_json(raw_body)
    except ValidationError as exc:
        logger.warning("Invalid chat request: %s", exc)
        raise
    user_query = payload.message.strip()
    if not user_query:
        return web.json_response({"error": "Message field is required."}, status=400)
    if not payload.conversation_id:
        return web.json_response(
            {"error": "conversation_id is required."},
            status=400,
        )

    run_attachments: list[RunAttachment] | None = None
    if payload.data:
        run_attachments = [
            RunAttachment(
                base64_encoded=attachment.base64,
                content_type=attachment.content_type,
                filename=attachment.filename,
            )
            for attachment in payload.data
        ]

    manager = request.app[ACTIVE_RUN_MANAGER_KEY]
    try:
        # HTTP "chat" is now only one channel vocabulary. Translate it here so
        # run ownership and execution do not depend on chat-specific semantics.
        info = await manager.start(AgentRunRequest(
            conversation_id=payload.conversation_id,
            message=user_query,
            attachments=run_attachments,
            profile_id=payload.profile_id,
        ))
    except ActiveRunConflictError:
        return web.json_response(
            {
                "error": (
                    "Another message is already being processed for this conversation, "
                    "possibly in another tab or window. Wait for it to finish, then try again."
                ),
            },
            status=409,
        )
    except ActiveRunManagerClosedError:
        return web.json_response(
            {"error": "Agent runtime is shutting down."},
            status=503,
        )

    # Subscribe immediately after start, without another await. Even a runner
    # that completes in one event-loop turn cannot be pruned before the initial
    # response captures its run.
    records = manager.subscribe(info.run_id, after_seq=0)
    return await stream_events(request, records)


async def chat_run_events_handler(request: Request) -> StreamResponse:
    """Replay missed run records after a cursor, then follow live records."""
    run_id = request.match_info["run_id"]
    raw_after = request.query.get("after", "0")
    try:
        after_seq = int(raw_after)
    except ValueError:
        return web.json_response({"error": "after must be an integer."}, status=400)

    manager = request.app[ACTIVE_RUN_MANAGER_KEY]
    try:
        records = manager.subscribe(run_id, after_seq=after_seq)
    except UnknownActiveRunError:
        return web.json_response(
            {"error": "Active run not found."},
            status=404,
        )
    except InvalidRunCursorError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return await stream_events(request, records)


async def stop_handler(request: Request) -> Response:
    """Request cooperative stop for a conversation's active agent run."""
    conversation_id = request.query.get("conversation_id")
    if not conversation_id:
        return web.json_response(
            {"error": "conversation_id is required."},
            status=400,
        )
    request.app[ACTIVE_RUN_MANAGER_KEY].request_stop(conversation_id)
    return web.json_response({"ok": True})


async def nudge_handler(request: Request) -> Response:
    """Send a nudge message to a running agent."""
    raw_body = await request.text()
    try:
        payload = NudgeRequest.model_validate_json(raw_body)
    except ValidationError as exc:
        logger.warning("Invalid nudge request: %s", exc)
        raise
    text = payload.message.strip()
    if not text:
        return web.json_response({"error": "message is required."}, status=400)
    if not is_turn_active(payload.conversation_id):
        return web.json_response(
            {"error": "No active turn for this conversation."},
            status=409,
        )
    nudge = queue_nudge(payload.agent_id, text)
    if nudge is None:
        return web.json_response(
            {"error": "The target agent is no longer running."},
            status=409,
        )
    return web.json_response({
        "ok": True,
        "nudge": {
            "id": nudge.id,
            "message": nudge.message,
            "agent_id": payload.agent_id,
        },
    })


async def list_nudges_handler(request: Request) -> Response:
    """List pending nudges for one agent in delivery order."""
    conversation_id = request.query.get("conversation_id")
    agent_id = request.query.get("agent_id")
    if not conversation_id or not agent_id:
        return web.json_response(
            {"error": "conversation_id and agent_id are required."},
            status=400,
        )
    nudges = [
        {"id": nudge.id, "message": nudge.message, "agent_id": agent_id}
        for nudge in list_nudges(agent_id)
    ]
    return web.json_response({"nudges": nudges})


async def delete_nudge_handler(request: Request) -> Response:
    """Delete a nudge if it is still pending for the requested agent."""
    conversation_id = request.query.get("conversation_id")
    agent_id = request.query.get("agent_id")
    if not conversation_id or not agent_id:
        return web.json_response(
            {"error": "conversation_id and agent_id are required."},
            status=400,
        )
    nudge = delete_nudge(agent_id, request.match_info["nudge_id"])
    if nudge is None:
        return web.json_response(
            {"error": "Nudge is no longer pending."},
            status=404,
        )
    return web.json_response({"ok": True})


def register_agent_run_routes(app: web.Application) -> None:
    """Register the HTTP channel adapter for agent runs."""
    app.router.add_route("POST", "/api/chat", chat_handler)
    app.router.add_route(
        "GET",
        "/api/chat/runs/{run_id}/events",
        chat_run_events_handler,
    )
    app.router.add_route("POST", "/api/chat/stop", stop_handler)
    app.router.add_route("POST", "/api/nudge", nudge_handler)
    app.router.add_route("GET", "/api/nudges", list_nudges_handler)
    app.router.add_route(
        "DELETE",
        "/api/nudges/{nudge_id}",
        delete_nudge_handler,
    )


__all__ = ["register_agent_run_routes"]
