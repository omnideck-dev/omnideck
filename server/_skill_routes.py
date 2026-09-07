"""HTTP route handlers for the editable skill API.

Skills are keyed by a stable ``id``; ``name`` is the editable display field and
must stay unique. Create generates an id when the client omits one; update keys
off the path id so a rename never changes it.
"""

from __future__ import annotations

import json
import logging
from uuid import uuid4

from aiohttp import web

from skills._policy import grants_restricted_tool_category, is_reserved_skill_id
from skills._store import (
    SkillRecord,
    delete_skill_record,
    get_skill_record,
    list_skill_records,
    save_skill_record,
)

logger = logging.getLogger(__name__)


def _public_skills() -> list[SkillRecord]:
    return [record for record in list_skill_records() if not is_reserved_skill_id(record.id)]


async def handle_list_skills(_request: web.Request) -> web.Response:
    """Return all skill records, sorted by name."""
    return web.json_response([r.model_dump() for r in _public_skills()])


async def handle_get_skill(request: web.Request) -> web.Response:
    """Return a single skill record by id."""
    skill_id = request.match_info["id"]
    if is_reserved_skill_id(skill_id):
        return web.json_response({"error": f"Skill '{skill_id}' not found"}, status=404)
    record = get_skill_record(skill_id)
    if record is None:
        return web.json_response({"error": f"Skill '{skill_id}' not found"}, status=404)
    return web.json_response(record.model_dump())


async def handle_create_skill(request: web.Request) -> web.Response:
    """Create a skill, generating an id when the client doesn't supply one."""
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response({"error": "Invalid JSON"}, status=400)
    body.setdefault("id", uuid4().hex[:12])
    if is_reserved_skill_id(body.get("id", "")) or grants_restricted_tool_category(body.get("tool_categories", [])):
        return web.json_response({"error": "Browser access is configured on the agent"}, status=400)
    try:
        saved = save_skill_record(SkillRecord.model_validate(body))
        return web.json_response(saved.model_dump(), status=201)
    except Exception as exc:
        logger.warning("Failed to create skill: %s", exc)
        return web.json_response({"error": str(exc)}, status=400)


async def handle_update_skill(request: web.Request) -> web.Response:
    """Update a skill in place; the path id wins so a rename keeps the id."""
    skill_id = request.match_info["id"]
    if is_reserved_skill_id(skill_id):
        return web.json_response({"error": f"Skill '{skill_id}' not found"}, status=404)
    if get_skill_record(skill_id) is None:
        return web.json_response({"error": f"Skill '{skill_id}' not found"}, status=404)
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response({"error": "Invalid JSON"}, status=400)
    body["id"] = skill_id
    if grants_restricted_tool_category(body.get("tool_categories", [])):
        return web.json_response({"error": "Browser access is configured on the agent"}, status=400)
    try:
        saved = save_skill_record(SkillRecord.model_validate(body))
        return web.json_response(saved.model_dump())
    except Exception as exc:
        logger.warning("Failed to update skill '%s': %s", skill_id, exc)
        return web.json_response({"error": str(exc)}, status=400)


async def handle_delete_skill(request: web.Request) -> web.Response:
    """Delete a skill record by id."""
    skill_id = request.match_info["id"]
    if is_reserved_skill_id(skill_id):
        return web.json_response({"error": f"Skill '{skill_id}' not found"}, status=404)
    if not delete_skill_record(skill_id):
        return web.json_response({"error": f"Skill '{skill_id}' not found"}, status=404)
    return web.Response(status=204)


def register_skill_routes(app: web.Application) -> None:
    """Register the skill API routes."""
    app.router.add_route("GET", "/api/skills", handle_list_skills)
    app.router.add_route("POST", "/api/skills", handle_create_skill)
    app.router.add_route("GET", "/api/skills/{id}", handle_get_skill)
    app.router.add_route("PUT", "/api/skills/{id}", handle_update_skill)
    app.router.add_route("DELETE", "/api/skills/{id}", handle_delete_skill)


__all__ = ["register_skill_routes"]
