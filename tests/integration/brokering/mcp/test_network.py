"""Endpoint policy on actual outbound requests, including redirects and DNS."""

import asyncio
import socket
from unittest.mock import AsyncMock

import httpx2
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from brokering.mcp_protocol._network import MCPTransport
from brokering.mcp_protocol import validated_address, mcp_http_client


@pytest.mark.parametrize("url", ["ftp://example.com/mcp", "https://user:secret@example.com/mcp", "https://example.com/mcp#fragment"])
async def test_invalid_urls_are_rejected_before_dns(url, monkeypatch):
    resolver = AsyncMock()
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolver)
    with pytest.raises(ValueError):
        await validated_address(httpx2.URL(url))
    resolver.assert_not_called()


@pytest.mark.parametrize("address", ["127.0.0.1", "::1", "10.0.0.1", "172.16.5.1", "192.168.1.1", "100.83.92.6", "fd7a:115c:a1e0::1"])
@pytest.mark.parametrize("scheme", ["http", "https"])
async def test_local_and_tailnet_servers_are_supported(address, scheme, monkeypatch):
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=[
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))
    ]))
    assert await validated_address(httpx2.URL(f"{scheme}://service.example/mcp")) == address


@pytest.mark.parametrize("addresses", [["169.254.169.254"], ["fe80::1"], ["0.0.0.0"], ["::"], ["224.0.0.1"], ["ff02::1"], ["8.8.8.8", "169.254.169.254"], []])
async def test_invalid_or_link_local_dns_answers_are_rejected(addresses, monkeypatch):
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=[
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)) for address in addresses
    ]))
    with pytest.raises(ValueError, match="unicast"):
        await validated_address(httpx2.URL("https://service.example/mcp"))


@pytest.mark.parametrize("addresses", [["8.8.8.8"], ["100.83.92.6", "8.8.8.8"]])
async def test_plain_http_requires_all_dns_answers_to_be_local(addresses, monkeypatch):
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=[
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 80)) for address in addresses
    ]))
    with pytest.raises(ValueError, match="Public MCP servers must use HTTPS"):
        await validated_address(httpx2.URL("http://service.example/mcp"))


async def test_pinned_dns_preserves_host_and_tls_name(monkeypatch):
    resolver = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolver)
    seen = []

    async def upstream(request):
        seen.append(request)
        return httpx2.Response(200, json={})

    transport = MCPTransport()
    await transport._transport.aclose()
    transport._transport = httpx2.MockTransport(upstream)
    async with httpx2.AsyncClient(transport=transport) as client:
        await client.get("https://service.example/mcp")
    assert seen[0].url.host == "8.8.8.8"
    assert seen[0].headers["Host"] == "service.example"
    assert seen[0].extensions["sni_hostname"] == "service.example"
    assert resolver.await_count == 1


async def test_redirect_does_not_forward_token():
    hits = []

    async def redirect(request):
        assert request.headers["Authorization"] == "Bearer fixture"
        return web.Response(status=302, headers={"Location": "/other"})

    async def other(request):
        hits.append(request.headers.get("Authorization"))
        return web.Response()

    app = web.Application()
    app.router.add_get("/mcp", redirect)
    app.router.add_get("/other", other)
    async with TestServer(app) as server:
        async with mcp_http_client(token="fixture") as client:
            with pytest.raises(ValueError, match="redirects are not supported"):
                await client.get(str(server.make_url("/mcp")))
    assert hits == []


async def test_bearer_token_is_restricted_to_the_connected_origin(monkeypatch):
    resolver = AsyncMock()
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolver)
    async with mcp_http_client(token="fixture", resource_endpoint="https://service.example/mcp") as client:
        with pytest.raises(ValueError, match="another origin"):
            await client.post("https://another.example/tools")
    resolver.assert_not_called()
