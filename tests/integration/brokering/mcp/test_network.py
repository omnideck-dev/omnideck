"""Endpoint policy on actual outbound requests, including redirects and DNS."""

import asyncio
import socket
from unittest.mock import AsyncMock

import httpx2
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from brokering.brokers.mcp_broker._network import PublicMCPTransport, validated_address, mcp_http_client


@pytest.mark.parametrize("url", ["http://example.com/mcp", "https://user:secret@example.com/mcp", "https://example.com/mcp#fragment"])
async def test_invalid_urls_are_rejected_before_dns(url, monkeypatch):
    resolver = AsyncMock()
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolver)
    with pytest.raises(ValueError):
        await validated_address(httpx2.URL(url))
    resolver.assert_not_called()


@pytest.mark.parametrize("addresses", [["127.0.0.1"], ["10.0.0.1"], ["169.254.169.254"], ["::1"], ["8.8.8.8", "192.168.1.1"]])
async def test_any_private_dns_answer_is_rejected(addresses, monkeypatch):
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=[
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)) for address in addresses
    ]))
    with pytest.raises(ValueError, match="public network"):
        await validated_address(httpx2.URL("https://service.example/mcp"))


async def test_pinned_dns_preserves_host_and_tls_name(monkeypatch):
    resolver = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolver)
    seen = []

    async def upstream(request):
        seen.append(request)
        return httpx2.Response(200, json={})

    transport = PublicMCPTransport()
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
        async with mcp_http_client(token="fixture", allow_loopback=True) as client:
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
