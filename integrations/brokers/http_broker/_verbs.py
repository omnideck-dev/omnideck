"""Verb dispatcher for the generic HTTP broker.

The whole surface is one verb, ``http_request``. The handler is where the
safety properties live:

- The path is resolved against ``BASE_URL`` and the resulting host must match
  the base's host — that's what stops a prompt-injected agent from pointing
  the integration's token at an attacker-controlled URL.
- The token header is attached server-side and the equivalent header names
  in the agent-supplied ``headers`` dict are dropped; the agent cannot
  override the auth.
- Redirects are not followed — a 3xx response is returned to the agent
  unchanged, so a follow-up call has to pass the same host check.
- Response bodies above the inline cap, and all non-text/json bodies
  regardless of size, are spilled to ``DOWNLOADS_DIR`` so they don't blow
  out the agent's context window.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import mimetypes
import secrets
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import aiohttp

from integrations._perms import ATTACHMENT_FILE_MODE
from integrations._rpc import RpcError
from integrations.permissions import Access, Capability, Permissions

logger = logging.getLogger(__name__)

# HTTP methods that don't change server state — only these are allowed
# when the integration was granted ``http:read`` rather than ``http:rw``.
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Every HTTP method the broker accepts. The broker doesn't invent novel
# ones; agents stick to the standard surface so server-side rejection is
# the upstream's job, not ours.
_ALL_METHODS = _READ_METHODS | frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Headers the agent must not be able to set on outbound requests. Authorization
# / X-Api-Key would let the agent swap out the integration's real token for
# something it controls; Cookie carries a parallel auth channel; Host would
# let the agent target a different virtual host on the same IP; hop-by-hop
# headers are meaningful only to the immediate transport and break things
# when forwarded.
_FORBIDDEN_REQUEST_HEADERS = frozenset({
    "authorization",
    "x-api-key",
    "cookie",
    "host",
    "content-length",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
})

# Response headers we don't echo back — same hop-by-hop list, plus
# Set-Cookie because the agent's tool layer has no cookie jar and a half-set
# cookie just clutters the response dict.
_HOP_BY_HOP_RESPONSE = frozenset({
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "set-cookie",
})

# Default body size cap before a response gets spilled to disk. Below this
# and the body comes back inline in the RPC result; above this and the
# bytes land in DOWNLOADS_DIR with the agent getting back a path.
_INLINE_BODY_CAP = 64 * 1024

# Hard ceiling on how much we'll read from the upstream regardless. Large
# enough to cover typical file downloads (PDFs, images) but small enough
# that a misbehaving upstream can't OOM the broker.
_MAX_RESPONSE_BYTES = 32 * 1024 * 1024

# Per-request timeout. Generous because some APIs are slow under load but
# bounded so a stuck upstream doesn't hang the whole broker.
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 30

_VERB_REQUIREMENT: dict[str, tuple[Capability, Access]] = {
    # Static gate: every dispatch needs at least http:read. The handler
    # promotes to http:read_write when the HTTP method is mutating —
    # method-level access depends on the request, not the verb name.
    "http_request": (Capability.HTTP, Access.READ),
}


_Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class VerbDispatcher:
    """Route ``http_request`` RPC calls into the aiohttp session."""

    def __init__(
        self,
        *,
        session: aiohttp.ClientSession,
        base_url: str,
        header_name: str,
        header_template: str,
        token: str,
        permissions: Permissions,
        downloads_dir: Path,
        inline_cap: int = _INLINE_BODY_CAP,
        max_response_bytes: int = _MAX_RESPONSE_BYTES,
        request_timeout_seconds: int = _DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/") + "/"
        # Cache the base's scheme+host for the host-match check; this is the
        # single safety property the dispatcher exists to enforce.
        parsed = urlsplit(self._base_url)
        if not parsed.scheme or not parsed.netloc:
            msg = f"BASE_URL is not absolute: {base_url!r}"
            raise ValueError(msg)
        self._base_scheme = parsed.scheme
        self._base_netloc = parsed.netloc
        self._header_name = header_name
        self._header_template = header_template
        self._token = token
        self._permissions = permissions
        self._downloads_dir = downloads_dir
        self._inline_cap = inline_cap
        self._max_response_bytes = max_response_bytes
        self._timeout = aiohttp.ClientTimeout(total=request_timeout_seconds)

        # Handler registry — keyed by verb name. Stays a one-entry dict for
        # now; the shape matches the other brokers so adding a future verb
        # (e.g. streaming) drops in cleanly.
        self._handlers: dict[str, _Handler] = {
            "http_request": self._handle_http_request,
        }

    async def dispatch(self, verb: str, args: dict[str, Any]) -> dict[str, Any]:
        """Entry point invoked by the RPC layer for every incoming frame."""
        requirement = _VERB_REQUIREMENT.get(verb)
        if requirement is None:
            msg = f"unknown verb: {verb}"
            raise RpcError("BAD_REQUEST", msg)

        cap, min_access = requirement
        granted = self._permissions.get(cap, Access.OFF)
        if granted < min_access:
            msg = (
                f"verb {verb!r} requires {cap.value}:{min_access.name.lower()}, "
                f"but this integration has {cap.value}:{granted.name.lower()}"
            )
            raise RpcError("PERMISSION_DENIED", msg)

        handler = self._handlers.get(verb)
        if handler is None:
            msg = f"verb not implemented: {verb}"
            raise RpcError("BAD_REQUEST", msg)

        return await handler(args)

    async def _handle_http_request(self, args: dict[str, Any]) -> dict[str, Any]:
        method = _require_method(args)

        # Dispatcher already enforced http:read; mutating methods need
        # the http:rw upgrade on top of that.
        if method not in _READ_METHODS:
            granted = self._permissions.get(Capability.HTTP, Access.OFF)
            if granted < Access.READ_WRITE:
                msg = (
                    f"method {method!r} requires http:read_write, "
                    f"but this integration has http:{granted.name.lower()}"
                )
                raise RpcError("PERMISSION_DENIED", msg)

        url = self._resolve_url(_require_str(args, "path"))
        query = _coerce_query(args.get("query"))
        headers = _build_outbound_headers(
            args.get("headers"), self._header_name, self._header_template, self._token,
        )
        body_bytes, body_content_type = _build_body(args)
        if body_content_type is not None and not _has_header(headers, "content-type"):
            headers["Content-Type"] = body_content_type

        try:
            async with self._session.request(
                method,
                url,
                params=query,
                headers=headers,
                data=body_bytes,
                timeout=self._timeout,
                allow_redirects=False,
            ) as resp:
                # Read up to the hard ceiling. aiohttp's read() returns
                # whatever's buffered; we cap to keep a misbehaving upstream
                # from eating all memory.
                payload = await resp.content.read(self._max_response_bytes + 1)
                response_status = resp.status
                response_headers = {
                    k: v
                    for k, v in resp.headers.items()
                    if k.lower() not in _HOP_BY_HOP_RESPONSE
                }
                response_content_type = resp.headers.get("Content-Type", "")
        except aiohttp.ClientError as exc:
            raise RpcError("UPSTREAM_ERROR", f"upstream request failed: {exc}") from exc
        except TimeoutError as exc:
            raise RpcError("UPSTREAM_TIMEOUT", "upstream request timed out") from exc

        # If we got more bytes than the ceiling, the response was bigger
        # than we'll handle — surface that rather than silently truncating.
        if len(payload) > self._max_response_bytes:
            raise RpcError(
                "RESPONSE_TOO_LARGE",
                f"response exceeded {self._max_response_bytes} bytes",
            )

        size = len(payload)
        # Inline only small text/json. Anything binary spills regardless of
        # size, anything large spills regardless of type. Everything else
        # inlines as UTF-8 text.
        is_textual = _is_textual_content_type(response_content_type)
        if is_textual and size <= self._inline_cap:
            try:
                body_text = payload.decode("utf-8")
            except UnicodeDecodeError:
                # Content-Type claimed text but bytes aren't valid UTF-8;
                # treat as binary and spill.
                body_text = None
            if body_text is not None:
                return {
                    "status": response_status,
                    "headers": response_headers,
                    "content_type": response_content_type,
                    "size": size,
                    "body": body_text,
                    "body_path": None,
                }

        # Spill path: write bytes to DOWNLOADS_DIR with a name that includes
        # an extension derived from the content type so the agent (and a
        # human inspecting the dir) can tell at a glance what landed.
        dest = _write_response_body(
            self._downloads_dir, payload, response_content_type,
        )
        return {
            "status": response_status,
            "headers": response_headers,
            "content_type": response_content_type,
            "size": size,
            "body": None,
            "body_path": str(dest),
        }

    def _resolve_url(self, path: str) -> str:
        """Join ``path`` onto the base URL and enforce same-host.

        Absolute URLs and protocol-relative ``//host/...`` paths both end up
        with a different ``netloc`` after ``urljoin`` and are rejected. Any
        difference in scheme (e.g. base ``https`` but resolved ``http``) is
        also rejected because TLS downgrade would expose the token in
        cleartext on the next hop.
        """
        joined = urljoin(self._base_url, path)
        parsed = urlsplit(joined)
        if parsed.scheme != self._base_scheme or parsed.netloc != self._base_netloc:
            msg = (
                f"path resolves off the integration's base URL: "
                f"got {parsed.scheme}://{parsed.netloc}, "
                f"expected {self._base_scheme}://{self._base_netloc}"
            )
            raise RpcError("BAD_REQUEST", msg)
        return joined


def _require_str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value:
        raise RpcError("BAD_REQUEST", f"{key!r} required (non-empty string)")
    return value


def _require_method(args: dict[str, Any]) -> str:
    method = _require_str(args, "method").upper()
    if method not in _ALL_METHODS:
        msg = f"method {method!r} not supported (allowed: {sorted(_ALL_METHODS)})"
        raise RpcError("BAD_REQUEST", msg)
    return method


def _coerce_query(value: Any) -> list[tuple[str, str]] | None:
    """Turn the optional ``query`` arg into the (key, value) list aiohttp wants.

    Accepts ``None``, a flat ``{str: str}`` mapping, or a ``{str: [str, ...]}``
    mapping for repeated keys. Anything else is a client bug.
    """
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise RpcError("BAD_REQUEST", "'query' must be an object")
    out: list[tuple[str, str]] = []
    for k, v in value.items():
        if not isinstance(k, str):
            raise RpcError("BAD_REQUEST", "'query' keys must be strings")
        if isinstance(v, str):
            out.append((k, v))
        elif isinstance(v, list):
            for item in v:
                if not isinstance(item, str):
                    raise RpcError(
                        "BAD_REQUEST", f"'query[{k!r}]' list items must be strings",
                    )
                out.append((k, item))
        else:
            raise RpcError(
                "BAD_REQUEST",
                f"'query[{k!r}]' must be a string or list of strings",
            )
    return out


def _build_outbound_headers(
    user_headers: Any, header_name: str, header_template: str, token: str,
) -> dict[str, str]:
    """Combine agent-supplied headers with the integration's auth header.

    Forbidden headers (auth, cookies, hop-by-hop) are silently dropped from
    the agent's input — failing loudly here would let a stray ``User-Agent``
    override break a whole agent call for no security gain. The integration's
    own auth header always wins.
    """
    out: dict[str, str] = {}
    if user_headers is not None:
        if not isinstance(user_headers, Mapping):
            raise RpcError("BAD_REQUEST", "'headers' must be an object")
        for k, v in user_headers.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise RpcError(
                    "BAD_REQUEST", "'headers' keys and values must be strings",
                )
            if k.lower() in _FORBIDDEN_REQUEST_HEADERS:
                continue
            out[k] = v
    out[header_name] = header_template.replace("{token}", token)
    return out


def _build_body(args: dict[str, Any]) -> tuple[bytes | None, str | None]:
    """Resolve the request body from ``body`` and ``body_b64``.

    Returns ``(payload_bytes, default_content_type)``. The content type is
    a default that the caller applies only if the user-supplied headers
    don't already set one — so a request like JSON-encoded body + explicit
    ``Content-Type: application/json-patch+json`` honors the user's intent.
    """
    body = args.get("body")
    body_b64 = args.get("body_b64")
    if body is not None and body_b64 is not None:
        raise RpcError(
            "BAD_REQUEST", "'body' and 'body_b64' are mutually exclusive",
        )

    if body is None and body_b64 is None:
        return None, None

    if body_b64 is not None:
        if not isinstance(body_b64, str):
            raise RpcError("BAD_REQUEST", "'body_b64' must be a base64 string")
        try:
            payload = base64.b64decode(body_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise RpcError(
                "BAD_REQUEST", f"'body_b64' is not valid base64: {exc}",
            ) from exc
        content_type = args.get("body_content_type")
        if content_type is not None and not isinstance(content_type, str):
            raise RpcError(
                "BAD_REQUEST", "'body_content_type' must be a string",
            )
        return payload, content_type or "application/octet-stream"

    if isinstance(body, str):
        return body.encode("utf-8"), "text/plain; charset=utf-8"
    if isinstance(body, (dict, list)):
        return (
            json.dumps(body, separators=(",", ":")).encode("utf-8"),
            "application/json",
        )
    raise RpcError(
        "BAD_REQUEST", "'body' must be a string, object, or array",
    )


def _has_header(headers: Mapping[str, str], name: str) -> bool:
    lowered = name.lower()
    return any(k.lower() == lowered for k in headers)


def _is_textual_content_type(content_type: str) -> bool:
    """True for JSON and text/* content types — the things safe to inline.

    Strict on purpose: anything outside JSON / text spills to disk. Avoids
    inlining things like ``application/xml``, ``application/x-www-form-urlencoded``
    response bodies — they're valid text but the agent rarely benefits from
    a megabyte of XML in its context.
    """
    if not content_type:
        return False
    base = content_type.split(";", 1)[0].strip().lower()
    if base == "application/json" or base.endswith("+json"):
        return True
    return base.startswith("text/")


def _write_response_body(dir_path: Path, payload: bytes, content_type: str) -> Path:
    """Write ``payload`` to a uniquely-named file under ``dir_path``."""
    dir_path.mkdir(parents=True, exist_ok=True)
    base_ct = content_type.split(";", 1)[0].strip() if content_type else ""
    ext = mimetypes.guess_extension(base_ct) if base_ct else None
    if not ext:
        ext = ".bin"
    name = f"http_{secrets.token_hex(6)}{ext}"
    dest = dir_path / name
    dest.write_bytes(payload)
    dest.chmod(ATTACHMENT_FILE_MODE)
    return dest
