"""HTTP route handlers for the artifacts hub.

Endpoints:
    GET    /api/artifacts                      — list artifacts (optionally one
                                                 conversation), reconciled against disk
    DELETE /api/artifacts/{id}                 — remove one entry; ?delete_file=true
                                                 also unlinks the file
    POST   /api/artifacts/prune-missing        — drop every entry whose file is gone
                                                 (optionally scoped by conversation_id)

The artifact files themselves are served by the existing virtual-computer file
route, so there is no download handler here.
"""

import logging

from aiohttp import web
from aiohttp.web import Request, Response

from artifacts import delete_artifact, list_artifacts, prune_missing, reconcile

logger = logging.getLogger(__name__)


def _is_truthy(value: str | None) -> bool:
    """Parse a query-string flag (?flag=true) into a bool."""
    return value is not None and value.lower() in ("1", "true", "yes")


async def list_artifacts_handler(request: Request) -> Response:
    """List artifacts, newest first, each tagged with its live on-disk status.

    With ?conversation_id=<id> the list is scoped to that conversation; without
    it, every artifact across all conversations is returned.
    """
    conversation_id = request.query.get("conversation_id")
    views = reconcile(list_artifacts(conversation_id))
    return web.json_response({"artifacts": [v.model_dump() for v in views]})


async def delete_artifact_handler(request: Request) -> Response:
    """Remove one artifact from the index; ?delete_file=true also unlinks it."""
    artifact_id = request.match_info["artifact_id"]
    delete_file = _is_truthy(request.query.get("delete_file"))
    removed = delete_artifact(artifact_id, delete_file=delete_file)
    if not removed:
        return web.json_response({"error": "Artifact not found"}, status=404)
    return web.Response(status=204)


async def prune_missing_handler(request: Request) -> Response:
    """Drop entries whose file no longer exists (optionally one conversation)."""
    conversation_id = request.query.get("conversation_id")
    removed = prune_missing(conversation_id)
    return web.json_response({"removed": removed})


def register_artifacts_routes(app: web.Application) -> None:
    """Register the artifacts hub routes on the application.

    The static prune-missing route is registered before the per-id wildcard so
    the matcher can't treat ``prune-missing`` as an artifact id.
    """
    app.router.add_route("GET", "/api/artifacts", list_artifacts_handler)
    app.router.add_route("POST", "/api/artifacts/prune-missing", prune_missing_handler)
    app.router.add_route("DELETE", "/api/artifacts/{artifact_id}", delete_artifact_handler)


__all__ = ["register_artifacts_routes"]
