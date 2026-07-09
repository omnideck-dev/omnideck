"""HTTP route handlers for the sharing API — export and import.

Export returns a bundle as a downloadable JSON document; import accepts one
back and creates fresh copies of everything inside it.
"""

from __future__ import annotations

import json
import logging
import re

from aiohttp import web

from sharing import (
    Bundle,
    build_profile_bundle,
    build_skill_bundle,
    import_bundle,
)

logger = logging.getLogger(__name__)


def _truthy(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


def _slug(name: str) -> str:
    """Filesystem-safe stem for a download filename, with a fallback."""
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip("-")
    return cleaned or "bundle"


def _download_response(bundle: Bundle, stem: str, ext: str) -> web.Response:
    """Serialize a bundle as an attachment download.

    ``ext`` is the type-specific extension (``agent`` / ``skill``) so a
    downloaded file's name signals what it holds; the payload is JSON either way.
    """
    body = json.dumps(bundle.model_dump(), indent=2)
    return web.Response(
        body=body.encode("utf-8"),
        content_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{_slug(stem)}.omnideck.{ext}"'},
    )


async def handle_export_profile(request: web.Request) -> web.Response:
    """Export a profile as a bundle.

    Query params:
        include_skills: embed the profile's attached skills (default false).
        include_model: keep the bound provider and model (default true).
    """
    profile_id = request.match_info["id"]
    include_skills = _truthy(request.query.get("include_skills", "false"))
    include_model = _truthy(request.query.get("include_model", "true"))
    try:
        bundle = build_profile_bundle(
            profile_id, include_skills=include_skills, include_model=include_model,
        )
    except KeyError:
        return web.json_response({"error": f"Profile '{profile_id}' not found"}, status=404)
    return _download_response(bundle, bundle.profiles[0].name, "agent")


async def handle_export_skill(request: web.Request) -> web.Response:
    """Export a single skill as a bundle."""
    skill_id = request.match_info["id"]
    try:
        bundle = build_skill_bundle(skill_id)
    except KeyError:
        return web.json_response({"error": f"Skill '{skill_id}' not found"}, status=404)
    return _download_response(bundle, bundle.skills[0].name, "skill")


async def handle_import_bundle(request: web.Request) -> web.Response:
    """Import a bundle, creating fresh copies of its profiles and skills."""
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response({"error": "Invalid JSON"}, status=400)
    try:
        bundle = Bundle.model_validate(body)
    except Exception as exc:
        logger.warning("Rejected bundle: %s", exc)
        return web.json_response({"error": "Not a valid omnideck export file"}, status=400)
    if not bundle.profiles and not bundle.skills:
        return web.json_response({"error": "Bundle is empty"}, status=400)
    try:
        summary = import_bundle(bundle)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response(summary.model_dump(), status=201)


def register_sharing_routes(app: web.Application) -> None:
    """Register the sharing (export/import) routes."""
    app.router.add_route("GET", "/api/profiles/{id}/export", handle_export_profile)
    app.router.add_route("GET", "/api/skills/{id}/export", handle_export_skill)
    app.router.add_route("POST", "/api/import", handle_import_bundle)


__all__ = ["register_sharing_routes"]
