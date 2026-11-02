"""SDK transport lifetime and bounded tool discovery; no broker or vault ownership."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from integrations.discovery import DiscoveredOperation, MAX_CATALOG_BYTES, MAX_OPERATIONS, mcp_operation_id, parse_discovered_operations
from ._network import mcp_http_client
from ._errors import MCPFailure, mcp_error_boundary, request_failure


@asynccontextmanager
async def connect(endpoint: str, *, token: str = "") -> AsyncIterator[Client]:
    # SDK transports own AnyIO cancel scopes, which must enter and exit in the
    # same task. Broker preparation and later activation/discard run in different
    # tasks; keep transport lifetime in a dedicated owner rather than moving its
    # context manager through the shared session slot.
    ready: asyncio.Future[Client] = asyncio.get_running_loop().create_future()
    stop = asyncio.Event()
    runtime_failed = False

    async def own_transport() -> None:
        nonlocal runtime_failed
        try:
            with mcp_error_boundary():
                async with mcp_http_client(token=token, resource_endpoint=endpoint) as http:
                    async with Client(streamable_http_client(endpoint, http_client=http), cache=None) as client:
                        ready.set_result(client)
                        await stop.wait()
        except BaseException as exc:
            if not ready.done():
                ready.set_exception(exc)
            else:
                # Pending SDK calls already receive a failed transport's
                # error. Retiring it later must not fail activation of a new
                # authenticated session. Actual teardown errors still surface.
                runtime_failed = not stop.is_set()
                raise

    owner = asyncio.create_task(own_transport(), name="mcp-transport")
    try:
        yield await ready
    finally:
        stop.set()
        if ready.cancelled() or not ready.done():
            owner.cancel()
        results = await asyncio.gather(owner, return_exceptions=True)
        if results and isinstance(results[0], Exception) and not runtime_failed:
            raise results[0]


async def discover(client: Client) -> tuple[DiscoveredOperation, ...]:
    with mcp_error_boundary():
        try:
            async with asyncio.timeout(30):
                return await _discover_pages(client)
        except TimeoutError as exc:
            raise request_failure(MCPFailure.DISCOVERY_TIMEOUT) from exc


async def _discover_pages(client: Client) -> tuple[DiscoveredOperation, ...]:
    entries: list[dict[str, Any]] = []
    cursor = None
    seen: set[str] = set()
    catalog_bytes = 2
    # The caller bounds the entire paginated discovery, not each page.
    while True:
        page = await client.list_tools(cursor=cursor)
        for tool in page.tools:
            entry = {
                "id": mcp_operation_id(tool.name), "title": tool.title or tool.name,
                "description": tool.description or "", "input_schema": tool.input_schema,
            }
            # Bound accumulation across pages, not just each HTTP response
            # or the final serialized catalog. A server can paginate one
            # huge schema at a time without exceeding the per-response cap.
            catalog_bytes += len(json.dumps(entry, allow_nan=False).encode()) + 2
            if catalog_bytes > MAX_CATALOG_BYTES:
                raise request_failure(MCPFailure.CATALOG_SIZE)
            entries.append(entry)
        if len(entries) > MAX_OPERATIONS:
            raise request_failure(MCPFailure.TOOL_COUNT)
        cursor = page.next_cursor
        if not cursor:
            break
        if cursor in seen or len(seen) >= MAX_OPERATIONS:
            raise ValueError("The MCP server returned invalid pagination.")
        seen.add(cursor)
    return parse_discovered_operations(json.dumps(entries))
