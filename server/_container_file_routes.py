"""HTTP routes for reading and writing files under the container home dir.

The frontend references container files by their real path instead of
base64-encoding them, so these routes serve the home directory over the host
volume mount and let the preview panel's source editor save edits back. Every
path is confined to the container home directory.
"""

import logging
from pathlib import Path

from aiohttp import web
from aiohttp.web import Request, Response, StreamResponse

from config import load_config

logger = logging.getLogger(__name__)


def _host_path_in_home(request: Request) -> Path | None:
    """Resolve the request's path under the container home.

    Returns the resolved path, or None if it escapes the home directory.
    """
    path = request.match_info.get("path", "")
    host_home = Path(load_config().virtual_computer.home_dir).resolve()
    host_path = (host_home / path).resolve()
    if not host_path.is_relative_to(host_home):
        return None
    return host_path


async def container_file_handler(request: Request) -> StreamResponse:
    """Serve files from the container's home directory via the host volume mount."""
    host_path = _host_path_in_home(request)
    if host_path is None:
        return web.Response(status=403, text="Forbidden")
    if not host_path.is_file():
        return web.Response(status=404, text="Not found")
    return web.FileResponse(host_path)


async def container_file_write_handler(request: Request) -> Response:
    """Overwrite a container-home file with the request body.

    Backs the preview panel's source editor: the frontend PUTs the edited text
    to the same URL it reads the file from. Writes stay inside the container
    home directory and only replace files that already exist — this route edits
    sources, it does not create new paths.
    """
    host_path = _host_path_in_home(request)
    if host_path is None:
        return web.Response(status=403, text="Forbidden")
    if not host_path.is_file():
        return web.Response(status=404, text="Not found")

    body = await request.read()
    host_path.write_bytes(body)
    return web.json_response({"ok": True})


def register_container_file_routes(app: web.Application) -> None:
    """Register the container-home file read/write routes.

    Files are served under the configured home prefix. A legacy prefix alias
    keeps stale references (old conversation history, agent-authored HTML)
    resolving to the same files; it can be removed once no stored content
    references the old path.

    GET returns the file; HEAD lets the preview poll Last-Modified/ETag without
    transferring the body; PUT saves edits from the source editor back to disk.
    """
    home_prefix = load_config().virtual_computer.home_dir
    for prefix in (home_prefix, "/home/computron"):
        app.router.add_route("GET", f"{prefix}/{{path:.*}}", container_file_handler)
        app.router.add_route("HEAD", f"{prefix}/{{path:.*}}", container_file_handler)
        app.router.add_route("PUT", f"{prefix}/{{path:.*}}", container_file_write_handler)


__all__ = [
    "container_file_handler",
    "container_file_write_handler",
    "register_container_file_routes",
]
