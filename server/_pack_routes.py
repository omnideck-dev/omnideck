"""HTTP route handlers for the pack API — export and import.

Export returns a pack as a downloadable JSON document; import accepts one
back and creates fresh copies of everything inside it.
"""

from __future__ import annotations

import json
import logging
import re

from aiohttp import web

from packs import (
    Pack,
    build_profile_pack,
    build_skill_pack,
    import_pack,
)

logger = logging.getLogger(__name__)

# Long names are free text, so cap the stem well under the 255-byte filename
# limit common to most filesystems.
_MAX_STEM = 64


def _truthy(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


def _slug(name: str) -> str:
    """Filesystem-safe stem for a download filename, with a fallback.

    Dots are replaced too, not just kept, so the only dots in the finished
    filename are the structural ones separating stem, kind, namespace and
    format. That also stops a name like ``.hidden`` from producing a dotfile.
    """
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-")
    return cleaned[:_MAX_STEM].strip("-") or "pack"


def _download_response(pack: Pack, stem: str, kind: str) -> web.Response:
    """Serialize a pack as an attachment download.

    The name is ``<item>.<kind>.omnideck.json``. Segments grow more general to
    the right, so ``.omnideck.json`` reads as one suffix meaning "an omnideck
    pack encoded as JSON" and a single glob matches every text pack whatever
    its kind. The last segment always names the real container format, so a
    future pack carrying a file tree ends in ``.omnideck.zip`` instead.
    """
    body = json.dumps(pack.model_dump(), indent=2)
    filename = f"{_slug(stem)}.{kind}.omnideck.json"
    return web.Response(
        body=body.encode("utf-8"),
        content_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def handle_export_profile(request: web.Request) -> web.Response:
    """Export a profile as a pack.

    Query params:
        include_skills: embed the profile's attached skills (default false).
        include_model: keep the bound provider and model (default true).
    """
    profile_id = request.match_info["id"]
    include_skills = _truthy(request.query.get("include_skills", "false"))
    include_model = _truthy(request.query.get("include_model", "true"))
    try:
        pack = build_profile_pack(
            profile_id, include_skills=include_skills, include_model=include_model,
        )
    except KeyError:
        return web.json_response({"error": f"Profile '{profile_id}' not found"}, status=404)
    return _download_response(pack, pack.profiles[0].name, "agent")


async def handle_export_skill(request: web.Request) -> web.Response:
    """Export a single skill as a pack."""
    skill_id = request.match_info["id"]
    try:
        pack = build_skill_pack(skill_id)
    except KeyError:
        return web.json_response({"error": f"Skill '{skill_id}' not found"}, status=404)
    return _download_response(pack, pack.skills[0].name, "skill")


async def handle_import_pack(request: web.Request) -> web.Response:
    """Import a pack, creating fresh copies of its profiles and skills.

    The body is the uploaded file's raw bytes. The client uploads it untouched,
    so deciding what the bytes are is this handler's job.
    """
    raw = await request.read()
    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("Rejected unparseable pack: %s", exc)
        return web.json_response({"error": "Not a valid omnideck export file"}, status=400)
    try:
        pack = Pack.model_validate(body)
    except Exception as exc:
        logger.warning("Rejected pack: %s", exc)
        return web.json_response({"error": "Not a valid omnideck export file"}, status=400)
    try:
        summary = import_pack(pack)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response(summary.model_dump(), status=201)


def register_pack_routes(app: web.Application) -> None:
    """Register the pack (export/import) routes."""
    app.router.add_route("GET", "/api/pack/export/profiles/{id}", handle_export_profile)
    app.router.add_route("GET", "/api/pack/export/skills/{id}", handle_export_skill)
    app.router.add_route("POST", "/api/pack/import", handle_import_pack)


__all__ = ["register_pack_routes"]
