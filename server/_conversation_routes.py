"""HTTP route handlers for conversation sessions.

Endpoints:
    GET    /api/conversations/sessions                        — list summaries
    GET    /api/conversations/archived                        — list archived summaries
    GET    /api/conversations/folders                         — list folders
    POST   /api/conversations/folders                         — create a folder
    PATCH  /api/conversations/folders/{id}                    — rename / recolor / reorder
    DELETE /api/conversations/folders/{id}                    — delete a folder
    POST   /api/conversations/sessions/{id}/resume            — load history + preview state
    POST   /api/conversations/sessions/{id}/title             — generate + persist a title
    POST   /api/conversations/sessions/{id}/archive           — archive a conversation
    POST   /api/conversations/sessions/{id}/unarchive         — restore an archived one
    PATCH  /api/conversations/sessions/{id}                   — rename / pin a conversation
    PUT    /api/conversations/sessions/{id}/preview-state     — persist preview tabs
    DELETE /api/conversations/sessions/{id}                   — delete a conversation
"""

import json
import logging
import re

from aiohttp import web
from aiohttp.web import Request, Response

from conversations import (
    archive_conversation,
    clear_folder_from_conversations,
    conversation_exists,
    create_folder,
    delete_conversation,
    delete_folder,
    folder_exists,
    generate_conversation_title,
    list_archived_conversations,
    list_conversations,
    list_folders,
    load_conversation_metadata,
    save_conversation_folder,
    save_conversation_pinned,
    save_conversation_title,
    save_preview_state,
    unarchive_conversation,
    update_folder,
)
from server._agent_runtime import ACTIVE_RUN_MANAGER_KEY
from server._conversation_cache import evict_conversation, resume_conversation

logger = logging.getLogger(__name__)

# The sidebar rename input caps at this many characters; the server enforces
# the same bound so a crafted request can't store an oversized title.
_MAX_TITLE_LEN = 50

# The folder name input caps here; enforced server-side for the same reason.
_MAX_FOLDER_NAME_LEN = 40

# A folder icon is a Bootstrap icon class. Constrain it to that shape so the
# value, which the UI renders straight into a className, can't smuggle in extra
# classes or markup.
_ICON_RE = re.compile(r"^bi-[a-z0-9-]{1,40}$")


async def list_conversations_handler(_request: Request) -> Response:
    """Return past conversation summaries for the conversations panel."""
    summaries = list_conversations()
    data = [s.model_dump() for s in summaries]
    return web.json_response(data)


async def delete_conversation_handler(request: Request) -> Response:
    """Delete a conversation and all its turns/history."""
    conversation_id = request.match_info["conversation_id"]
    manager = request.app[ACTIVE_RUN_MANAGER_KEY]
    if manager.active_for_conversation(conversation_id) is not None:
        return web.json_response(
            {"error": "This conversation is still running. Stop it before deleting."},
            status=409,
        )
    found = delete_conversation(conversation_id)
    if not found:
        return web.json_response({"error": "Conversation not found"}, status=404)
    await evict_conversation(conversation_id)
    return web.Response(status=204)


async def list_archived_handler(_request: Request) -> Response:
    """Return summaries of archived conversations for the archived panel."""
    summaries = list_archived_conversations()
    data = [s.model_dump() for s in summaries]
    return web.json_response(data)


async def archive_conversation_handler(request: Request) -> Response:
    """Archive a conversation, moving it out of the active list."""
    conversation_id = request.match_info["conversation_id"]
    manager = request.app[ACTIVE_RUN_MANAGER_KEY]
    if manager.active_for_conversation(conversation_id) is not None:
        return web.json_response(
            {"error": "This conversation is still running. Stop it before archiving."},
            status=409,
        )
    found = archive_conversation(conversation_id)
    if not found:
        return web.json_response({"error": "Conversation not found"}, status=404)
    await evict_conversation(conversation_id)
    return web.Response(status=204)


async def unarchive_conversation_handler(request: Request) -> Response:
    """Restore an archived conversation back into the active list."""
    conversation_id = request.match_info["conversation_id"]
    found = unarchive_conversation(conversation_id)
    if not found:
        return web.json_response({"error": "Conversation not found"}, status=404)
    return web.Response(status=204)


async def update_conversation_handler(request: Request) -> Response:
    """Rename and/or pin a conversation.

    Accepts a JSON object with any of:
        title:     str        — new title; blank reverts to the first-message fallback
        pinned:    bool       — whether the conversation floats to the Pinned section
        folder_id: str | None — folder to file it into; null removes it from its folder
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

    # Validate folder_id before writing anything: an unknown folder is a
    # client bug, not something to silently persist as a dangling reference.
    if "folder_id" in body:
        folder_id = body["folder_id"]
        if folder_id is not None and not isinstance(folder_id, str):
            return web.json_response(
                {"error": "folder_id must be a string or null"},
                status=400,
            )
        if isinstance(folder_id, str) and not folder_exists(folder_id):
            return web.json_response({"error": "Folder not found"}, status=400)

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

    if "folder_id" in body:
        save_conversation_folder(conversation_id, body["folder_id"])

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
            {"error": "first_message must be a non-empty string"},
            status=400,
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
    manager = request.app[ACTIVE_RUN_MANAGER_KEY]
    active = manager.active_for_conversation(conversation_id)
    if active is None and not conversation_exists(conversation_id):
        return web.json_response({"error": "Conversation not found"}, status=404)
    data = await resume_conversation(conversation_id)

    active_run = None
    if active is not None:
        resume_after_seq = 0
        for event in reversed(data["events"]):
            event_id = event.get("id")
            if not isinstance(event_id, str):
                continue
            sequence = manager.sequence_for_event(active.run_id, event_id)
            if sequence is not None:
                resume_after_seq = sequence
                break
        active_run = {
            "run_id": active.run_id,
            "status": "running",
            "last_seq": active.last_seq,
            "resume_after_seq": resume_after_seq,
        }

    return web.json_response(
        {
            "conversation_id": conversation_id,
            "messages": data["messages"],
            "events": data["events"],
            "browser_tabs": data["browser_tabs"],
            "terminal": data["terminal"],
            "preview_state": data["preview_state"],
            "profile_id": data["profile_id"],
            "active_run": active_run,
        }
    )


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


async def list_folders_handler(_request: Request) -> Response:
    """Return all conversation folders for the sidebar."""
    folders = list_folders()
    return web.json_response([f.model_dump() for f in folders])


async def create_folder_handler(request: Request) -> Response:
    """Create a folder from a JSON body: ``{"name": str, "icon"?: str}``."""
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "Body must be a JSON object"}, status=400)
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        return web.json_response({"error": "name must be a non-empty string"}, status=400)
    icon = body.get("icon")
    if icon is not None and (not isinstance(icon, str) or not _ICON_RE.match(icon)):
        return web.json_response({"error": "icon must be a bootstrap icon class"}, status=400)
    folder = create_folder(name.strip()[:_MAX_FOLDER_NAME_LEN], icon=icon)
    return web.json_response(folder.model_dump(), status=201)


async def update_folder_handler(request: Request) -> Response:
    """Rename, re-icon, or reorder a folder.

    Accepts any of ``name`` (str), ``icon`` (bootstrap icon class), ``order`` (int).
    """
    folder_id = request.match_info["folder_id"]
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "Body must be a JSON object"}, status=400)

    name = body.get("name")
    if "name" in body and (not isinstance(name, str) or not name.strip()):
        return web.json_response({"error": "name must be a non-empty string"}, status=400)
    icon = body.get("icon")
    if "icon" in body and (not isinstance(icon, str) or not _ICON_RE.match(icon)):
        return web.json_response({"error": "icon must be a bootstrap icon class"}, status=400)
    order = body.get("order")
    if "order" in body and not isinstance(order, int):
        return web.json_response({"error": "order must be an integer"}, status=400)

    folder = update_folder(
        folder_id,
        name=name if "name" in body else None,
        icon=icon if "icon" in body else None,
        order=order if "order" in body else None,
    )
    if folder is None:
        return web.json_response({"error": "Folder not found"}, status=404)
    return web.json_response(folder.model_dump())


async def delete_folder_handler(request: Request) -> Response:
    """Delete a folder and clear the folder tag from its member conversations."""
    folder_id = request.match_info["folder_id"]
    found = delete_folder(folder_id)
    if not found:
        return web.json_response({"error": "Folder not found"}, status=404)
    # Members fall back to the normal date-grouped listing once unfiled.
    clear_folder_from_conversations(folder_id)
    return web.Response(status=204)


def register_conversation_routes(app: web.Application) -> None:
    """Register conversation session routes on the application.

    The collection route is registered before the per-id wildcard so the
    aiohttp matcher doesn't accidentally treat `sessions` as an id.
    """
    app.router.add_route("GET", "/api/conversations/sessions", list_conversations_handler)
    app.router.add_route("GET", "/api/conversations/archived", list_archived_handler)
    app.router.add_route("GET", "/api/conversations/folders", list_folders_handler)
    app.router.add_route("POST", "/api/conversations/folders", create_folder_handler)
    app.router.add_route("PATCH", "/api/conversations/folders/{folder_id}", update_folder_handler)
    app.router.add_route("DELETE", "/api/conversations/folders/{folder_id}", delete_folder_handler)
    app.router.add_route("POST", "/api/conversations/sessions/{conversation_id}/resume", resume_conversation_handler)
    app.router.add_route("POST", "/api/conversations/sessions/{conversation_id}/title", generate_title_handler)
    app.router.add_route("POST", "/api/conversations/sessions/{conversation_id}/archive", archive_conversation_handler)
    app.router.add_route(
        "POST",
        "/api/conversations/sessions/{conversation_id}/unarchive",
        unarchive_conversation_handler,
    )
    app.router.add_route(
        "PUT",
        "/api/conversations/sessions/{conversation_id}/preview-state",
        save_preview_state_handler,
    )
    app.router.add_route("PATCH", "/api/conversations/sessions/{conversation_id}", update_conversation_handler)
    app.router.add_route("DELETE", "/api/conversations/sessions/{conversation_id}", delete_conversation_handler)


__all__ = ["register_conversation_routes"]
