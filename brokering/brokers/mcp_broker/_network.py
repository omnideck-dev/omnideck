"""Public-network-only MCP HTTP transport with DNS checked at connection time."""

import asyncio
import ipaddress
import logging
import socket
from collections.abc import AsyncIterator

import httpx2


def quiet_protocol_logs() -> None:
    """SDK exception/HTTP logs can contain OAuth responses, URLs and state.

    These namespaces are owned exclusively by the MCP integration. Application
    lifecycle logs remain enabled, with sanitized errors at their boundaries.
    """
    for namespace in ("mcp", "httpx2", "httpcore2"):
        library_logger = logging.getLogger(namespace)
        library_logger.handlers = [logging.NullHandler()]
        library_logger.propagate = False


async def validated_address(url: httpx2.URL, *, allow_loopback: bool = False) -> str:
    """Resolve once, reject private answers, and return the address to connect."""
    if url.username or url.password or url.fragment or not url.host:
        raise ValueError("Use an HTTPS server URL without embedded credentials or a fragment.")
    if url.scheme != "https" and not (allow_loopback and url.scheme == "http"):
        raise ValueError("MCP servers must use HTTPS.")
    async with asyncio.timeout(10):
        answers = await asyncio.get_running_loop().getaddrinfo(
            url.host, url.port or (443 if url.scheme == "https" else 80), type=socket.SOCK_STREAM,
        )
    addresses = [ipaddress.ip_address(answer[4][0]) for answer in answers]
    if not addresses or any(not ip.is_global and not (allow_loopback and ip.is_loopback) for ip in addresses):
        raise ValueError("MCP endpoints must resolve to public network addresses.")
    if url.scheme == "http" and any(not ip.is_loopback for ip in addresses):
        raise ValueError("HTTP is only allowed for local test fixtures.")
    return str(addresses[0])


class _BoundedStream(httpx2.AsyncByteStream):
    def __init__(self, stream: httpx2.AsyncByteStream) -> None:
        self._stream = stream

    async def __aiter__(self) -> AsyncIterator[bytes]:
        total = 0
        async for chunk in self._stream:
            total += len(chunk)
            if total > 4 * 1024 * 1024:
                raise ValueError("The MCP server response is too large.")
            yield chunk

    async def aclose(self) -> None:
        await self._stream.aclose()


class PublicMCPTransport(httpx2.AsyncBaseTransport):
    """Pin approved DNS answers while preserving HTTPS SNI and the Host header.

    Keepalive is disabled because pooling by pinned IP could reuse a TLS
    connection across different logical hostnames sharing that IP. No proxies,
    cookies, or redirects are inherited from the user's environment.
    """

    def __init__(
        self, *, allow_loopback: bool = False, background_resource: str | None = None,
        resource_endpoint: str | None = None,
    ) -> None:
        self._allow_loopback = allow_loopback
        self._background_resource = str(httpx2.URL(background_resource)) if background_resource else None
        self._resource_url = httpx2.URL(resource_endpoint) if resource_endpoint else None
        self._transport = httpx2.AsyncHTTPTransport(
            trust_env=False, limits=httpx2.Limits(max_keepalive_connections=0),
        )

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        if self._resource_url is not None and request.headers.get("Authorization", "").lower().startswith("bearer "):
            expected = self._resource_url
            if (request.url.scheme, request.url.host, request.url.port) != (expected.scheme, expected.host, expected.port):
                raise ValueError("An MCP access token cannot be sent to another origin.")
        address = await validated_address(request.url, allow_loopback=self._allow_loopback)
        pinned = httpx2.Request(
            request.method, request.url.copy_with(host=address), headers=request.headers,
            stream=request.stream, extensions={**request.extensions, "sni_hostname": request.url.host},
        )
        response = await self._transport.handle_async_request(pinned)
        # The SDK has its own same-origin redirect loop even when httpx's
        # follow_redirects is false. Reject here so the network policy also
        # applies to metadata, registration and token requests.
        if response.status_code in {301, 302, 303, 307, 308}:
            await response.aclose()
            raise ValueError("Use the service's final URL; MCP redirects are not supported.")
        # A background refresh must never turn into registration, consent, or
        # insufficient-scope escalation. Stop before feeding the challenge to
        # the SDK's interactive OAuth state machine.
        if str(request.url) == self._background_resource and response.status_code in {401, 403}:
            await response.aclose()
            raise ValueError("Sign in again to restore provider access.")
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            await response.aclose()
            raise ValueError("Compressed MCP responses are not supported.")
        assert isinstance(response.stream, httpx2.AsyncByteStream)
        response.stream = _BoundedStream(response.stream)
        return response

    async def aclose(self) -> None:
        await self._transport.aclose()


def mcp_http_client(
    *, auth: httpx2.Auth | None = None, token: str = "", allow_loopback: bool = False,
    background_resource: str | None = None,
    resource_endpoint: str | None = None,
) -> httpx2.AsyncClient:
    quiet_protocol_logs()
    return httpx2.AsyncClient(
        transport=PublicMCPTransport(allow_loopback=allow_loopback, background_resource=background_resource,
                                    resource_endpoint=resource_endpoint), auth=auth,
        headers={"Accept-Encoding": "identity", **({"Authorization": f"Bearer {token}"} if token else {})},
        timeout=httpx2.Timeout(30, connect=10), follow_redirects=False, trust_env=False,
    )
