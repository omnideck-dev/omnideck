"""Agent tool: issue an authenticated HTTP request through a configured integration."""

from __future__ import annotations

import base64
import logging
import mimetypes
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from config import load_config
from integrations import broker_client

logger = logging.getLogger(__name__)


async def call_api(
    integration_id: str,
    method: str,
    path: str,
    query: dict | None = None,
    headers: dict | None = None,
    body: dict | None = None,
    file_path: str | None = None,
) -> str:
    """Make an HTTP request to a configured API and return the response.

    The integration owns the base URL and the auth token; you supply a path
    that resolves against that base. Paths pointing at any other host are
    rejected. Use ``body`` for a JSON request body, or ``file_path`` to upload
    a local file's contents.

    Args:
        integration_id: Which configured API to call through.
        method: HTTP method, e.g. "GET" or "POST".
        path: Path under the API's base URL, e.g. "/user/repos".
        query: Query parameters as a flat object, e.g. {"state": "open"}.
        headers: Extra request headers. The auth header is added automatically.
        body: JSON request body as an object. Do not combine with file_path.
        file_path: Local file to upload as the request body. Do not combine with body.

    Returns:
        The response status and body as text. Large or binary responses are
        saved to a file and the path is returned instead.
    """
    if body is not None and file_path is not None:
        return "Cannot set both 'body' and 'file_path' on one request."

    rpc_args: dict[str, Any] = {"method": method, "path": path}
    if query is not None:
        rpc_args["query"] = query
    if headers is not None:
        rpc_args["headers"] = headers
    if body is not None:
        rpc_args["body"] = body
    if file_path is not None:
        try:
            file_bytes = Path(file_path).read_bytes()
        except OSError as exc:
            return f"Cannot read file {file_path!r}: {exc}"
        rpc_args["body_b64"] = base64.b64encode(file_bytes).decode("ascii")
        rpc_args["body_content_type"] = (
            mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        )

    app_sock = load_config().integrations.app_sock_path
    try:
        result = await broker_client.call(
            integration_id, "http_request", rpc_args, app_sock_path=app_sock,
        )
    except broker_client.IntegrationNotConnected:
        return f"Integration {integration_id!r} is not connected."
    except broker_client.IntegrationWriteDenied:
        return (
            f"Method {method.upper()!r} is not permitted: "
            f"integration {integration_id!r} is read-only."
        )
    except broker_client.IntegrationError as exc:
        logger.warning(
            "call_api(%r, %s %s) failed: %s",
            integration_id, method.upper(), path, exc,
        )
        return f"Request through {integration_id!r} failed: {exc}"

    return _format_response(result)


def _format_response(result: dict[str, Any]) -> str:
    """Format the broker's response dict into the plain text the agent reads."""
    status = result.get("status")
    content_type = result.get("content_type") or ""
    size = result.get("size", 0)
    body_text = result.get("body")
    body_path = result.get("body_path")
    location = (result.get("headers") or {}).get("Location")

    lines = [f"{status} ({size} bytes, content-type: {content_type or 'unknown'})"]
    if location:
        # 3xx responses carry a Location header the agent uses to decide on
        # a follow-up call — surface it explicitly rather than burying it in
        # the headers dump.
        lines.append(f"location: {location}")

    if body_path:
        lines.append(f"body written to {body_path}")
    elif body_text is not None:
        lines.append("")
        lines.append(body_text)
    return "\n".join(lines)


def build_call_api_tool(integration_ids: Iterable[str]) -> Callable[..., Any]:
    """Turn-scoped wrapper whose docstring advertises the current IDs."""
    ids = sorted(integration_ids)
    ids_line = ", ".join(repr(i) for i in ids) if ids else "(none registered)"

    async def _call_api(
        integration_id: str,
        method: str,
        path: str,
        query: dict | None = None,
        headers: dict | None = None,
        body: dict | None = None,
        file_path: str | None = None,
    ) -> str:
        return await call_api(
            integration_id, method, path,
            query=query, headers=headers, body=body, file_path=file_path,
        )

    _call_api.__name__ = call_api.__name__
    _call_api.__doc__ = (
        "Make an HTTP request to a configured API and return the response. "
        "Each integration owns its base URL and auth token; you supply a path "
        "under that base URL and the token is added automatically. Paths "
        "pointing at another host are rejected. "
        f"Valid integration IDs: {ids_line}.\n\n"
        "Args:\n"
        "    integration_id: Which configured API to call through.\n"
        "    method: HTTP method, e.g. \"GET\" or \"POST\".\n"
        "    path: Path under the API's base URL, e.g. \"/user/repos\".\n"
        "    query: Query parameters as a flat object, e.g. {\"state\": \"open\"}.\n"
        "    headers: Extra request headers. The auth header is added automatically.\n"
        "    body: JSON request body as an object. Do not combine with file_path.\n"
        "    file_path: Local file to upload as the body. Do not combine with body.\n\n"
        "Returns:\n"
        "    The response status and body as text. Large or binary responses are\n"
        "    saved to a file and the path is returned instead.\n"
    )
    return _call_api
