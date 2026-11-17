"""MCP HTTP transport for public, local and tailnet servers with pinned DNS."""

import asyncio
import ipaddress
import logging
import socket
from collections.abc import AsyncIterator

import httpx2

from ._errors import MCPFailure, request_failure
from ._compression import DecompressedStream, MAX_RESPONSE_BYTES


def quiet_protocol_logs() -> None:
    """SDK exception/HTTP logs can contain OAuth responses, URLs and state.

    These namespaces are owned exclusively by the MCP integration. Application
    lifecycle logs remain enabled, with sanitized errors at their boundaries.
    """
    for namespace in ("mcp", "httpx2", "httpcore2"):
        library_logger = logging.getLogger(namespace)
        library_logger.handlers = [logging.NullHandler()]
        library_logger.propagate = False


_LOCAL_NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "fc00::/7",
))


def _local_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return ip.is_loopback or any(ip in network for network in _LOCAL_NETWORKS)


async def validated_address(url: httpx2.URL) -> str:
    """Resolve once and accept public or local unicast server addresses."""
    if url.username or url.password or url.fragment or not url.host:
        raise ValueError("Use an HTTP or HTTPS server URL without embedded credentials or a fragment.")
    if url.scheme not in {"http", "https"}:
        raise ValueError("MCP servers must use HTTP or HTTPS.")
    async with asyncio.timeout(10):
        answers = await asyncio.get_running_loop().getaddrinfo(
            url.host, url.port or (443 if url.scheme == "https" else 80), type=socket.SOCK_STREAM,
        )
    addresses = [ipaddress.ip_address(answer[4][0]) for answer in answers]
    if not addresses or any(
        ip.is_multicast or ip.is_unspecified or ip.is_link_local
        or not (ip.is_global or _local_address(ip)) for ip in addresses
    ):
        raise ValueError("MCP endpoints must resolve to public or local unicast addresses; link-local addresses are not allowed.")
    if url.scheme == "http" and any(not _local_address(ip) for ip in addresses):
        raise ValueError("Public MCP servers must use HTTPS; HTTP is only allowed for local and tailnet servers.")
    return str(addresses[0])


class _BoundedStream(httpx2.AsyncByteStream):
    def __init__(self, stream: httpx2.AsyncByteStream) -> None:
        self._stream = stream

    async def __aiter__(self) -> AsyncIterator[bytes]:
        total = 0
        try:
            async for chunk in self._stream:
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    # The SDK handles StreamError without killing the entire
                    # session. The request boundary retains our local reason.
                    raise httpx2.StreamError(str(request_failure(MCPFailure.RESPONSE_SIZE)))
                yield chunk
        except httpx2.TimeoutException as exc:
            raise httpx2.StreamError(str(request_failure(MCPFailure.NETWORK_TIMEOUT))) from exc

    async def aclose(self) -> None:
        await self._stream.aclose()


class MCPTransport(httpx2.AsyncBaseTransport):
    """Pin approved DNS answers while preserving HTTPS SNI and the Host header.

    Keepalive is disabled because pooling by pinned IP could reuse a TLS
    connection across different logical hostnames sharing that IP. No proxies,
    cookies, or redirects are inherited from the user's environment.
    """

    def __init__(
        self, *, background_resource: str | None = None,
        resource_endpoint: str | None = None,
    ) -> None:
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
        address = await validated_address(request.url)
        pinned = httpx2.Request(
            request.method, request.url.copy_with(host=address), headers=request.headers,
            stream=request.stream, extensions={**request.extensions, "sni_hostname": request.url.host},
        )
        try:
            response = await self._transport.handle_async_request(pinned)
        except httpx2.TimeoutException as exc:
            raise request_failure(MCPFailure.NETWORK_TIMEOUT) from exc
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
        # Only an authenticated resource POST can trigger background renewal.
        # A GET/SSE failure or tool-result text is not this request's rejection.
        if (self._background_resource is None and self._resource_url == request.url
                and request.method == "POST" and response.status_code == 401
                and request.headers.get("Authorization", "").lower().startswith("bearer ")
                and response.headers.get("WWW-Authenticate", "").lower().startswith("bearer")):
            await response.aclose()
            raise request_failure(MCPFailure.AUTH_REJECTED)
        encoding = response.headers.get("content-encoding", "identity").strip().lower()
        if encoding not in {"identity", "gzip", "deflate"}:
            await response.aclose()
            raise ValueError("Unsupported MCP response encoding; use gzip, deflate, or identity.")
        assert isinstance(response.stream, httpx2.AsyncByteStream)
        response.stream = _BoundedStream(response.stream)
        if encoding != "identity":
            if request.method != "HEAD" and response.status_code not in {204, 304}:
                response.stream = DecompressedStream(response.stream, encoding)
            # The stream now supplies decoded bytes. Prevent HTTPX from decoding
            # again or describing their size with the compressed Content-Length.
            del response.headers["content-encoding"]
            response.headers.pop("content-length", None)
        return response

    async def aclose(self) -> None:
        await self._transport.aclose()


def mcp_http_client(
    *, auth: httpx2.Auth | None = None, token: str = "",
    background_resource: str | None = None,
    resource_endpoint: str | None = None,
) -> httpx2.AsyncClient:
    quiet_protocol_logs()
    return httpx2.AsyncClient(
        transport=MCPTransport(background_resource=background_resource,
                                    resource_endpoint=resource_endpoint), auth=auth,
        headers={"Accept-Encoding": "gzip, deflate", **({"Authorization": f"Bearer {token}"} if token else {})},
        timeout=httpx2.Timeout(30, connect=10), follow_redirects=False, trust_env=False,
    )
