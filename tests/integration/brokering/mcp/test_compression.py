"""Real HTTP compression through the same transport used for OAuth and MCP."""

import asyncio
import gzip
import json
import os
import zlib
from contextlib import asynccontextmanager

import httpx2
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from brokering._rpc import RpcError
from brokering.mcp_protocol._compression import DecompressedStream, MAX_RESPONSE_BYTES
from brokering.mcp_protocol import MCPRequestError, mcp_error_boundary
from brokering.mcp_protocol import mcp_http_client
from brokering.brokers.mcp_broker.client import MCPDispatcher
from brokering.mcp_protocol import connect, discover


@asynccontextmanager
async def response_server(body, encoding, *, chunk_size=4096, status=200):
    async def handle(request):
        assert request.headers["Accept-Encoding"] == "gzip, deflate"
        response = web.StreamResponse(status=status, headers={
            "Content-Encoding": encoding, "Content-Type": "text/event-stream",
        })
        await response.prepare(request)
        try:
            for offset in range(0, len(body), chunk_size):
                await response.write(body[offset:offset + chunk_size])
            await response.write_eof()
        except ConnectionResetError:
            pass  # A bounded client may stop reading before the server finishes.
        return response

    app = web.Application()
    app.router.add_route("*", "/mcp", handle)
    async with TestServer(app) as server:
        async with mcp_http_client() as client:
            yield client, str(server.make_url("/mcp"))


@pytest.mark.parametrize("encoding,compress", [("gzip", gzip.compress), ("deflate", zlib.compress)])
@pytest.mark.parametrize("chunk_size", [1, 4096])
async def test_compressed_http_response_decodes_once(encoding, compress, chunk_size):
    body = 'data: {"message":"hello 世界"}\n\n'.encode() * 50
    async with response_server(compress(body), encoding, chunk_size=chunk_size) as (client, url):
        response = await client.get(url)
        assert response.content == body
        assert "content-encoding" not in response.headers
        assert "content-length" not in response.headers


@pytest.mark.parametrize("encoding,compress", [("gzip", gzip.compress), ("deflate", zlib.compress)])
async def test_compressed_expansion_enforces_response_limit(encoding, compress):
    body = compress(b"x" * (MAX_RESPONSE_BYTES + 1))
    assert len(body) < 8192
    async with response_server(body, encoding) as (client, url):
        with pytest.raises(MCPRequestError) as error, mcp_error_boundary():
            await client.get(url)
        assert error.value.code == "MCP_RESPONSE_SIZE_LIMIT"


async def test_compressed_wire_bytes_are_also_limited():
    # Incompressible input has a wire size above the limit even though its
    # decoded content fits; both limits must remain independently enforced.
    body = gzip.compress(os.urandom(MAX_RESPONSE_BYTES))
    assert len(body) > MAX_RESPONSE_BYTES
    async with response_server(body, "gzip") as (client, url):
        with pytest.raises(MCPRequestError) as error, mcp_error_boundary():
            await client.get(url)
        assert error.value.code == "MCP_RESPONSE_SIZE_LIMIT"


async def test_gzip_members_share_one_expanded_limit():
    member = gzip.compress(b"x" * (MAX_RESPONSE_BYTES // 2))
    async with response_server(member + member, "gzip") as (client, url):
        assert len((await client.get(url)).content) == MAX_RESPONSE_BYTES
    async with response_server(member + member + gzip.compress(b"x"), "gzip") as (client, url):
        with pytest.raises(httpx2.StreamError, match="4 MiB"):
            await client.get(url)


@pytest.mark.parametrize("body,encoding", [
    (b"not gzip", "gzip"),
    (gzip.compress(b"hello")[:-1], "gzip"),
    (gzip.compress(b"hello")[:-8] + b"\x00" * 8, "gzip"),
    (zlib.compress(b"hello")[:-1], "deflate"),
    (zlib.compress(b"hello") + b"garbage", "deflate"),
])
async def test_malformed_compression_fails(body, encoding):
    async with response_server(body, encoding) as (client, url):
        with pytest.raises(httpx2.StreamError, match="compressed MCP response"):
            await client.get(url)


@pytest.mark.parametrize("encoding", ["br", "gzip, deflate"])
async def test_unadvertised_encodings_are_rejected(encoding):
    async with response_server(b"anything", encoding) as (client, url):
        with pytest.raises(ValueError, match="Unsupported MCP response encoding"):
            await client.get(url)


async def test_gzip_event_is_delivered_before_stream_finishes():
    release = asyncio.Event()

    async def handle(request):
        response = web.StreamResponse(headers={"Content-Encoding": "gzip", "Content-Type": "text/event-stream"})
        await response.prepare(request)
        compressor = zlib.compressobj(wbits=zlib.MAX_WBITS | 16)
        await response.write(compressor.compress(b"data: first\n\n") + compressor.flush(zlib.Z_SYNC_FLUSH))
        await release.wait()
        await response.write(compressor.flush())
        return response

    app = web.Application()
    app.router.add_get("/mcp", handle)
    async with TestServer(app) as server, mcp_http_client() as client:
        try:
            async with asyncio.timeout(2), client.stream("GET", str(server.make_url("/mcp"))) as response:
                assert await anext(response.aiter_lines()) == "data: first"
        finally:
            release.set()


async def test_decoder_bounds_each_output_allocation_and_closes_source():
    class Source(httpx2.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield gzip.compress(b"x" * MAX_RESPONSE_BYTES)

        async def aclose(self):
            self.closed = True

    source = Source()
    stream = DecompressedStream(source, "gzip")
    chunks = [chunk async for chunk in stream]
    assert sum(map(len, chunks)) == MAX_RESPONSE_BYTES
    assert max(map(len, chunks)) <= 64 * 1024
    await stream.aclose()
    assert source.closed


@pytest.mark.parametrize("method,status", [("HEAD", 200), ("GET", 204), ("GET", 304)])
async def test_bodyless_responses_do_not_require_compressed_payload(method, status):
    async with response_server(b"", "gzip", status=status) as (client, url):
        assert (await client.request(method, url)).content == b""


@pytest.mark.parametrize("encoding,compress", [("gzip", gzip.compress), ("deflate", zlib.compress)])
@pytest.mark.parametrize("oversized", [False, True])
async def test_mcp_discovery_and_tool_call_with_compressed_responses(encoding, compress, oversized):
    calls = []

    async def handle(request):
        if request.method != "POST":
            return web.Response(status=405)
        message = await request.json()
        if "id" not in message:
            return web.Response(status=202)
        envelope = {"jsonrpc": "2.0", "id": message["id"]}
        if message["method"] == "server/discover":
            envelope["error"] = {"code": -32601, "message": "Unknown method"}
        elif message["method"] == "initialize":
            envelope["result"] = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
                                  "serverInfo": {"name": "compressed fixture", "version": "1"}}
        elif message["method"] == "tools/list":
            envelope["result"] = {"tools": [{"name": "echo", "inputSchema": {
                "type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"],
            }}]}
        elif message["method"] == "tools/call":
            calls.append(message["params"])
            value = "x" * (MAX_RESPONSE_BYTES + 1) if oversized else message["params"]["arguments"]["value"]
            envelope["result"] = {"content": [{"type": "text", "text": value}]}
        else:
            pytest.fail(f"Unexpected method: {message['method']}")
        return web.Response(body=compress(json.dumps(envelope).encode()), content_type="application/json",
                            headers={"Content-Encoding": encoding})

    app = web.Application()
    app.router.add_route("*", "/mcp", handle)
    async with TestServer(app) as server:
        async with connect(str(server.make_url("/mcp"))) as client:
            operations = await discover(client)
            assert [operation.id for operation in operations] == ["mcp.echo"]
            dispatcher = MCPDispatcher(client, operations)
            dispatcher.replace_operation_grants(frozenset({"mcp.echo"}))
            if oversized:
                with pytest.raises(RpcError) as error:
                    await dispatcher.dispatch("mcp.echo", {"value": "hello"})
                assert error.value.code == "MCP_RESPONSE_SIZE_LIMIT"
                assert "has not retried" in error.value.message
            else:
                result = await dispatcher.dispatch("mcp.echo", {"value": "hello"})
                assert result["content"][0]["text"] == "hello"
    assert calls == [{"name": "echo", "arguments": {"value": "hello"}, "_meta": {}}]
