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


async def http_request(
    integration_id: str,
    method: str,
    path: str,
    query: dict[str, str | list[str]] | None = None,
    headers: dict[str, str] | None = None,
    body: str | dict[str, Any] | list[Any] | None = None,
    file_path: str | None = None,
) -> str:
    """Send one HTTP request through a configured token-auth integration.

    The integration owns the base URL and the auth header — the agent
    supplies a path that resolves against that base. Paths that resolve
    off-host are refused server-side. The agent can include a request body
    as a string or JSON-encodable object via ``body``, or upload a local
    file's bytes by setting ``file_path`` (mutually exclusive with ``body``).

    Args:
        integration_id: Identifier of the configured http integration to
            call through. The token attached to the request is whichever
            secret was bound to that integration at setup.
        method: HTTP method. ``GET``, ``HEAD``, ``OPTIONS`` are allowed on
            read-only integrations; ``POST``, ``PUT``, ``PATCH``, ``DELETE``
            need a read-write integration.
        path: Request path. Resolved against the integration's base URL —
            absolute URLs and paths that escape the base's host are refused.
        query: Optional query parameters. Values may be strings or lists of
            strings (lists repeat the key in the final URL).
        headers: Optional extra request headers. The integration's auth
            header is attached server-side and cannot be overridden here;
            ``Authorization`` / ``Cookie`` and similar are silently dropped.
        body: Optional request body. Strings are sent as ``text/plain``;
            dicts and lists are JSON-encoded with ``application/json``.
            Mutually exclusive with ``file_path``.
        file_path: Optional path to a local file whose bytes become the
            request body. The content type is guessed from the extension
            (``application/octet-stream`` fallback). Mutually exclusive
            with ``body``.

    Returns:
        Plain text — a short status + content-type line, then either the
        inline body or a "<n bytes written to <path>" line when the response
        was binary or larger than the inline cap. Errors return a short notice.
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
            "http_request(%r, %s %s) failed: %s",
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


def build_http_request_tool(integration_ids: Iterable[str]) -> Callable[..., Any]:
    """Turn-scoped wrapper whose docstring advertises the current IDs."""
    ids = sorted(integration_ids)
    ids_line = ", ".join(repr(i) for i in ids) if ids else "(none registered)"

    async def _http_request(
        integration_id: str,
        method: str,
        path: str,
        query: dict[str, str | list[str]] | None = None,
        headers: dict[str, str] | None = None,
        body: str | dict[str, Any] | list[Any] | None = None,
        file_path: str | None = None,
    ) -> str:
        return await http_request(
            integration_id, method, path,
            query=query, headers=headers, body=body, file_path=file_path,
        )

    _http_request.__name__ = http_request.__name__
    _http_request.__doc__ = (
        "Send one HTTP request through a configured token-auth integration. "
        "Each integration is scoped to a single base URL; the path you supply "
        "is resolved against that base and paths that escape the host are "
        "refused. The integration's auth header is attached server-side. "
        f"Valid integration IDs: {ids_line}.\n\n"
        "Args:\n"
        "    integration_id: Which integration to send the request through.\n"
        "    method: HTTP method (GET/HEAD/OPTIONS on read-only integrations;\n"
        "        POST/PUT/PATCH/DELETE need read-write).\n"
        "    path: Request path relative to the integration's base URL.\n"
        "    query: Optional query params; values may be strings or list of strings.\n"
        "    headers: Optional extra headers (Authorization/Cookie are stripped).\n"
        "    body: Optional request body — string sent as text/plain, dict/list\n"
        "        sent as JSON. Mutually exclusive with file_path.\n"
        "    file_path: Optional local file whose bytes become the request body;\n"
        "        content type is guessed from the extension.\n\n"
        "Returns:\n"
        "    Plain text — '<status> (<n> bytes, content-type: ...)' followed by\n"
        "    the inline body, or a 'body written to <path>' line for binary or\n"
        "    large responses.\n"
    )
    return _http_request
