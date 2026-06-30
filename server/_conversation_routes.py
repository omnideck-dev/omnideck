"""HTTP route handlers for conversation sessions.

Endpoints:
    GET    /api/conversations/sessions                        — list summaries
    POST   /api/conversations/sessions/{id}/resume            — load history + preview state
    POST   /api/conversations/sessions/{id}/title             — generate + persist a title
    PATCH  /api/conversations/sessions/{id}                   — rename / pin a conversation
    PUT    /api/conversations/sessions/{id}/preview-state     — persist preview tabs
    POST   /api/conversations/sessions/{id}/preview-state/focus-file
                                                              — focus a file on next open
    DELETE /api/conversations/sessions/{id}                   — delete a conversation
"""

import json
import logging

from aiohttp import web
from aiohttp.web import Request, Response

from conversations import (
    conversation_exists,
    delete_conversation,
    generate_conversation_title,
    list_conversations,
    load_conversation_metadata,
    mark_file_focused,
    save_conversation_pinned,
    save_conversation_title,
    save_preview_state,
)
from server._conversation_cache import resume_conversation

logger = logging.getLogger(__name__)

# The sidebar rename input caps at this many characters; the server enforces
# the same bound so a crafted request can't store an oversized title.
_MAX_TITLE_LEN = 50


async def list_conversations_handler(_request: Request) -> Response:
    """Return past conversation summaries for the conversations panel."""
    summaries = list_conversations()
    data = [s.model_dump() for s in summaries]
    return web.json_response(data)


async def delete_conversation_handler(request: Request) -> Response:
    """Delete a conversation and all its turns/history."""
    conversation_id = request.match_info["conversation_id"]
    found = delete_conversation(conversation_id)
    if not found:
        return web.json_response({"error": "Conversation not found"}, status=404)
    return web.Response(status=204)


async def update_conversation_handler(request: Request) -> Response:
    """Rename and/or pin a conversation.

    Accepts a JSON object with any of:
        title:  str   — new title; blank reverts to the first-message fallback
        pinned: bool  — whether the conversation floats to the Pinned section
    """
    conversation_id = request.match_info["conversation_id"]
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "Body must be a JSON object"}, status=400)
    if not conversation_exists(conversation_id):
        return web.json_response({"error": "Conversation not found"}, status=404)

    if "title" in body:
        title = body["title"]
        if not isinstance(title, str):
            return web.json_response({"error": "title must be a string"}, status=400)
        # Blank input falls back to the conversation's first message in the UI,
        # so persist an empty title rather than rejecting it.
        save_conversation_title(conversation_id, title.strip()[:_MAX_TITLE_LEN])

    if "pinned" in body:
        pinned = body["pinned"]
        if not isinstance(pinned, bool):
            return web.json_response({"error": "pinned must be a boolean"}, status=400)
        save_conversation_pinned(conversation_id, pinned)

    return web.Response(status=204)


async def generate_title_handler(request: Request) -> Response:
    """Generate and persist a title for a conversation from its first message.

    The frontend calls this when a new conversation starts, concurrently with
    the first turn, so the generated title lands in the sidebar without waiting
    for the turn to finish. The first message is supplied in the body rather
    than read from disk, so this doesn't depend on the event log having been
    written yet.

    Idempotent: if a title already exists (a prior call, or a manual rename),
    the existing one is returned without regenerating — re-fires are cheap and
    a user rename is never clobbered.
    """
    conversation_id = request.match_info["conversation_id"]
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "Body must be a JSON object"}, status=400)
    first_message = body.get("first_message")
    if not isinstance(first_message, str) or not first_message.strip():
        return web.json_response(
            {"error": "first_message must be a non-empty string"}, status=400,
        )

    existing = load_conversation_metadata(conversation_id).get("title")
    if isinstance(existing, str) and existing.strip():
        return web.json_response({"title": existing})

    try:
        title = await generate_conversation_title(first_message)
    except Exception:
        logger.exception("Failed to generate title for conversation %s", conversation_id)
        return web.json_response({"error": "Title generation failed"}, status=502)

    save_conversation_title(conversation_id, title)
    return web.json_response({"title": title})


async def resume_conversation_handler(request: Request) -> Response:
    """Resume a past conversation by loading its full-fidelity history."""
    conversation_id = request.match_info["conversation_id"]
    data = await resume_conversation(conversation_id)
    if data is None:
        return web.json_response({"error": "Conversation not found"}, status=404)
    return web.json_response({
        "conversation_id": conversation_id,
        "messages": data["messages"],
        "events": data["events"],
        "preview_state": data["preview_state"],
        "profile_id": data["profile_id"],
    })


async def save_preview_state_handler(request: Request) -> Response:
    """Persist the user's preview-panel tab state for a conversation.

    The body is the full preview-state dict; it replaces any prior value.
    """
    conversation_id = request.match_info["conversation_id"]
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "Body must be a JSON object"}, status=400)
    save_preview_state(conversation_id, body)
    return web.Response(status=204)


async def focus_file_handler(request: Request) -> Response:
    """Mark a file as the open, active tab so reopening the conversation focuses it.

    Body: ``{"path": "<absolute file path>"}``. Merges into the existing preview
    state without clobbering the other panel flags; the file is then served and
    restored by the normal resume path.
    """
    conversation_id = request.match_info["conversation_id"]
    if not conversation_exists(conversation_id):
        return web.json_response({"error": "Conversation not found"}, status=404)
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    path = body.get("path") if isinstance(body, dict) else None
    if not isinstance(path, str) or not path:
        return web.json_response({"error": "Body must include a 'path' string"}, status=400)
    mark_file_focused(conversation_id, path)
    return web.Response(status=204)


def register_conversation_routes(app: web.Application) -> None:
    """Register conversation session routes on the application.

    The collection route is registered before the per-id wildcard so the
    aiohttp matcher doesn't accidentally treat `sessions` as an id.
    """
    app.router.add_route("GET", "/api/conversations/sessions", list_conversations_handler)
    app.router.add_route("POST", "/api/conversations/sessions/{conversation_id}/resume", resume_conversation_handler)
    app.router.add_route("POST", "/api/conversations/sessions/{conversation_id}/title", generate_title_handler)
    app.router.add_route("PUT", "/api/conversations/sessions/{conversation_id}/preview-state", save_preview_state_handler)
    app.router.add_route("POST", "/api/conversations/sessions/{conversation_id}/preview-state/focus-file", focus_file_handler)
    app.router.add_route("PATCH", "/api/conversations/sessions/{conversation_id}", update_conversation_handler)
    app.router.add_route("DELETE", "/api/conversations/sessions/{conversation_id}", delete_conversation_handler)


__all__ = ["register_conversation_routes"]
