"""LLM proxy broker: inject auth header, forward HTTP traffic over a UDS.

The supervisor spawns this with credentials and provider info in the
environment. It starts an aiohttp HTTP server on a Unix Domain Socket,
then serves as a transparent HTTP proxy that injects the real auth header on
every forwarded request. Startup and live updates validate configuration only;
upstream key validation remains the provider wizard's responsibility.

Streaming responses (SSE / chunked transfer encoding) pass through
unmodified — the proxy writes chunks to the SDK client as they arrive
from the upstream API.

Exit codes (same contract as email_broker):
- 0: clean shutdown
- 1: network unreachable or internal error
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
from aiohttp import web

from brokering._env import capture_connection_fields, env_required
from brokering._control import BrokerControl, run_with_control
from brokering._session_slot import BrokerSessionSlot
from brokering._perms import PROCESS_UMASK, SOCKET_MODE, disable_core_dumps
from brokering._exit_codes import CLEAN_SHUTDOWN

os.umask(PROCESS_UMASK)
disable_core_dumps()

logger = logging.getLogger("llm_proxy")

# Headers that must not be forwarded; they're hop-by-hop and meaningful
# only for the immediate transport layer, not the end-to-end exchange.
_HOP_BY_HOP = frozenset({
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
})

# Auth headers each provider expects; we strip these from the SDK client
# request (which carries a placeholder) and inject the real key.
_AUTH_HEADERS_TO_STRIP = frozenset({"authorization", "x-api-key"})

# The proxy forwards whole LLM request bodies untouched. For a chat request
# that body is the entire conversation transcript, which grows to many
# megabytes on a long conversation. aiohttp's default cap is 1 MiB, small
# enough to reject a normal long conversation before it ever reaches the
# upstream. Disable the cap (0 = no limit) so the proxy stays transparent to
# body size and lets the upstream API enforce the real request limits.
_NO_REQUEST_BODY_LIMIT = 0


def _make_auth_headers(provider: str, api_key: str) -> dict[str, str]:
    """Return the auth header(s) to inject for this provider."""
    if provider == "anthropic":
        return {"x-api-key": api_key}
    return {"Authorization": f"Bearer {api_key}"}



@dataclass(frozen=True, repr=False)
class ProxyCredentials:
    """The proxy's broker session: immutable auth/config, not an HTTP client."""

    api_key: str
    provider: str
    base_url: str


@asynccontextmanager
async def create_session(connection_fields: dict[str, str]) -> AsyncIterator[ProxyCredentials]:
    """Create a proxy session without making paid or provider-specific calls.

    Only credentials/configuration are replaced. The process-wide HTTP client
    lives outside this session and keeps its pool across credential updates.
    """
    base = connection_fields["LLM_BASE_URL"].rstrip("/")
    parsed = urlsplit(base)
    key = connection_fields["LLM_API_KEY"]
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("invalid provider base URL")
    if not key or "\r" in key or "\n" in key:
        raise ValueError("invalid API key header")
    yield ProxyCredentials(key, connection_fields["LLM_PROVIDER"], base)


async def _run() -> int:
    connection_id = env_required("INTEGRATION_ID")
    socket_path = Path(env_required("BROKER_SOCKET"))
    connection_fields = capture_connection_fields(("LLM_API_KEY", "LLM_PROVIDER", "LLM_BASE_URL"))
    session_slot = BrokerSessionSlot(create_session)
    prepared_session = await session_slot.prepare(connection_fields)
    await prepared_session.activate()
    connection_fields.clear()

    log = logging.getLogger(f"llm_proxy[{connection_id}]")

    # Skip startup key validation — the wizard's model probe (GET /api/models)
    # exercises the real SDK path and gives the user immediate feedback. The
    # broker just proxies; it doesn't need to second-guess the key.

    # One persistent upstream session for all proxied requests. Reusing a session
    # keeps the TCP connection pool warm and avoids per-request TLS handshake overhead.
    # auto_decompress=False: the proxy must forward raw bytes with their original
    # Content-Encoding intact — the SDK client handles decompression itself.
    upstream_session = aiohttp.ClientSession(auto_decompress=False)

    async def proxy_handler(request: web.Request) -> web.StreamResponse:
        # Keep this request's URL and key together, even across a live update.
        credentials = session_slot.current
        # Reconstruct the full upstream URL from the base plus the request's
        # relative URL (path + query string).
        url = credentials.base_url + str(request.rel_url)

        # Forward all request headers except hop-by-hop and auth placeholders;
        # then inject the real credentials.
        headers: dict[str, str] = {}
        for k, v in request.headers.items():
            kl = k.lower()
            if kl in _HOP_BY_HOP or kl in _AUTH_HEADERS_TO_STRIP or kl == "host":
                continue
            headers[k] = v
        headers.update(_make_auth_headers(credentials.provider, credentials.api_key))

        body = await request.read()

        try:
            async with upstream_session.request(
                request.method,
                url,
                headers=headers,
                data=body or None,
                # Long timeout to accommodate streaming completions that may
                # run for many seconds (or minutes for long generation tasks).
                timeout=aiohttp.ClientTimeout(total=600),
                allow_redirects=False,
            ) as upstream_resp:
                response = web.StreamResponse(
                    status=upstream_resp.status,
                    reason=upstream_resp.reason,
                )
                for k, v in upstream_resp.headers.items():
                    kl = k.lower()
                    # Drop content-length so the response can stream as chunked
                    # encoding without a mismatch if the upstream sends a length.
                    if kl in _HOP_BY_HOP or kl == "content-length":
                        continue
                    response.headers[k] = v

                await response.prepare(request)
                async for chunk in upstream_resp.content.iter_any():
                    await response.write(chunk)
                await response.write_eof()
                return response
        except aiohttp.ClientError as exc:
            log.error("upstream request failed: %s", exc)
            return web.Response(status=502, text=f"Bad Gateway: {exc}")

    # Remove stale socket from a crashed or previous run. The supervisor
    # un-links sockets on clean shutdown; a SIGKILL leaves them behind.
    if socket_path.exists() or socket_path.is_symlink():
        socket_path.unlink()

    app = web.Application(client_max_size=_NO_REQUEST_BODY_LIMIT)
    app.router.add_route("*", "/{path_info:.*}", proxy_handler)

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.UnixSite(runner, str(socket_path))
    await site.start()
    # chmod AFTER bind — aiohttp creates the socket with the process umask
    # (0o077) which blocks all group/other access. We need 0o660 so the
    # omnideck UID (in the broker group) can connect.
    socket_path.chmod(SOCKET_MODE)

    log.info("listening on %s (provider=%s)", socket_path, session_slot.current.provider)

    try:
        await run_with_control(asyncio.Event().wait(), BrokerControl(None, session_slot.prepare))
    except asyncio.CancelledError:
        log.info("shutting down")
    finally:
        await upstream_session.close()
        await runner.cleanup()
        await session_slot.close()

    return CLEAN_SHUTDOWN


def main() -> None:
    """Console entry point — configure logging, run the async body, exit with its return code."""
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="[%(name)s] %(asctime)s %(levelname)s %(message)s",
    )
    try:
        code = asyncio.run(_run())
    except KeyboardInterrupt:
        code = CLEAN_SHUTDOWN
    sys.exit(code)


if __name__ == "__main__":
    main()
