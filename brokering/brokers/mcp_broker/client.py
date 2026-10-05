"""SDK-backed discovery and invocation; no browser or vault access."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp import Client
from mcp.types import CallToolRequest, CallToolRequestParams, CallToolResult
from mcp.client.streamable_http import streamable_http_client

from brokering._rpc import RpcError
from integrations.discovery import (
    DiscoveredOperation, MAX_CATALOG_BYTES, MAX_OPERATIONS, mcp_operation_id, parse_discovered_operations,
)
from ._network import mcp_http_client


@asynccontextmanager
async def connect(endpoint: str, *, token: str = "", allow_loopback: bool = False) -> AsyncIterator[Client]:
    # SDK transports own AnyIO cancel scopes, which must enter and exit in the
    # same task. Broker preparation and later activation/discard run in different
    # tasks; keep transport lifetime in a dedicated owner rather than moving its
    # context manager through the shared session slot.
    ready: asyncio.Future[Client] = asyncio.get_running_loop().create_future()
    stop = asyncio.Event()

    async def own_transport() -> None:
        try:
            async with mcp_http_client(token=token, allow_loopback=allow_loopback, resource_endpoint=endpoint) as http:
                async with Client(streamable_http_client(endpoint, http_client=http), cache=None) as client:
                    ready.set_result(client)
                    await stop.wait()
        except BaseException as exc:
            if not ready.done():
                ready.set_exception(exc)
            else:
                raise

    owner = asyncio.create_task(own_transport(), name="mcp-transport")
    try:
        yield await ready
    finally:
        stop.set()
        if ready.cancelled() or not ready.done():
            owner.cancel()
        results = await asyncio.gather(owner, return_exceptions=True)
        if results and isinstance(results[0], Exception):
            raise results[0]


async def discover(client: Client) -> tuple[DiscoveredOperation, ...]:
    entries: list[dict[str, Any]] = []
    cursor = None
    seen = set()
    catalog_bytes = 2
    async with asyncio.timeout(30):
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
                    raise ValueError("The server's tool catalog is too large.")
                entries.append(entry)
            if len(entries) > MAX_OPERATIONS:
                raise ValueError("The MCP server has too many tools.")
            cursor = page.next_cursor
            if not cursor:
                break
            if cursor in seen or len(seen) >= MAX_OPERATIONS:
                raise ValueError("The MCP server returned invalid pagination.")
            seen.add(cursor)
    return parse_discovered_operations(json.dumps(entries))


class MCPDispatcher:
    """Enforce exact connection grants before any remote tools/call request."""

    def __init__(self, client: Client, operations: tuple[DiscoveredOperation, ...]) -> None:
        self._client = client
        self._available = frozenset(operation.id for operation in operations)
        self._grants: frozenset[str] = frozenset()

    def replace_operation_grants(self, grants: frozenset[str]) -> None:
        self._grants = grants

    async def dispatch(self, operation_id: str, args: dict[str, Any]) -> dict[str, Any]:
        if operation_id not in self._grants:
            raise RpcError("PERMISSION_DENIED", "This tool is not enabled for this integration.")
        if operation_id not in self._available:
            raise RpcError("NOT_FOUND", "This tool is no longer available. Reconnect to refresh tools.")
        try:
            async with asyncio.timeout(60):
                # Use the single-request API: never automatically satisfy
                # elicitation/sampling or retry a potentially mutating tool.
                # The higher-level call_tool also validates remote output
                # schemas. omnideck deliberately has no output-schema contract;
                # use the SDK's public typed request API, without resolving
                # untrusted schema references or following interaction rounds.
                result = await self._client.session.send_request(
                    CallToolRequest(params=CallToolRequestParams(name=operation_id[4:], arguments=args)),
                    CallToolResult,
                )
            payload = result.model_dump(mode="json", by_alias=True, exclude_none=True)
            if len(json.dumps(payload).encode()) > 2 * 1024 * 1024:
                raise ValueError("oversized result")
            return payload
        except Exception as exc:
            raise RpcError("UPSTREAM", "The remote tool failed. Check the connection and provider access.") from exc
