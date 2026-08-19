"""HTTP route handlers for the artifacts hub.

Endpoints:
    GET    /api/artifacts                      — list artifacts (optionally one
                                                 conversation), reconciled against disk
    GET    /api/artifacts/{id}                 — get one artifact by stable id
    DELETE /api/artifacts/{id}                 — remove one entry; ?delete_file=true
                                                 also unlinks the file
    POST   /api/artifacts/prune-missing        — drop every entry whose file is gone
                                                 (optionally scoped by conversation_id)

The artifact files themselves are served by the existing virtual-computer file
route, so there is no download handler here.
"""

import logging
from collections.abc import Callable

from aiohttp import web
from aiohttp.web import Request, Response

from artifacts import delete_artifact, get_artifact, list_artifacts, prune_missing, reconcile
from conversations import conversation_exists, load_conversation_metadata

logger = logging.getLogger(__name__)


def _is_truthy(value: str | None) -> bool:
    """Parse a query-string flag (?flag=true) into a bool."""
    return value is not None and value.lower() in ("1", "true", "yes")


def _title_resolver() -> Callable[[str], str | None]:
    """Return a function mapping a conversation id to its display title.

    Caches per id so a list spanning many artifacts in one conversation reads
    that conversation's metadata once. Returns None when the conversation no
    longer exists, so the UI can show it as deleted and disable "open".
    """
    cache: dict[str, str | None] = {}

    def title_for(conversation_id: str) -> str | None:
        if conversation_id not in cache:
            if conversation_exists(conversation_id):
                title = (load_conversation_metadata(conversation_id).get("title") or "").strip()
                cache[conversation_id] = title or "Untitled"
            else:
                cache[conversation_id] = None
        return cache[conversation_id]

    return title_for


async def list_artifacts_handler(request: Request) -> Response:
    """List artifacts, newest first, each tagged with its live on-disk status.

    With ?conversation_id=<id> the list is scoped to that conversation; without
    it, every artifact across all conversations is returned. Each entry also
    carries its source conversation's title (or null if that conversation is
    gone), joined in here from the conversation store.
    """
    conversation_id = request.query.get("conversation_id")
    views = reconcile(list_artifacts(conversation_id))
    title_for = _title_resolver()
    for view in views:
        view.conversation_title = title_for(view.conversation_id)
    return web.json_response({"artifacts": [v.model_dump() for v in views]})


async def delete_artifact_handler(request: Request) -> Response:
    """Remove one artifact from the index; ?delete_file=true also unlinks it."""
    artifact_id = request.match_info["artifact_id"]
    delete_file = _is_truthy(request.query.get("delete_file"))
    removed = delete_artifact(artifact_id, delete_file=delete_file)
    if not removed:
        return web.json_response({"error": "Artifact not found"}, status=404)
    return web.Response(status=204)


async def get_artifact_handler(request: Request) -> Response:
    """Return one artifact with the same live overlays as the collection."""
    artifact = get_artifact(request.match_info["artifact_id"])
    if artifact is None:
        return web.json_response({"error": "Artifact not found"}, status=404)
    view = reconcile([artifact])[0]
    view.conversation_title = _title_resolver()(view.conversation_id)
    return web.json_response(view.model_dump())


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
    app.router.add_route("GET", "/api/artifacts/{artifact_id}", get_artifact_handler)
    app.router.add_route("DELETE", "/api/artifacts/{artifact_id}", delete_artifact_handler)


__all__ = ["register_artifacts_routes"]
