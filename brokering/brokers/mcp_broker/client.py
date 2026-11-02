"""Broker-side tool approval enforcement and single-request invocation."""

import asyncio
import json
from typing import Any

from mcp import Client
from mcp.types import CallToolRequest, CallToolRequestParams, CallToolResult

from brokering._rpc import RpcError
from brokering._operation_errors import UNKNOWN_OUTCOME
from brokering.mcp_protocol import MCPFailure, MCPRequestError, mcp_error_boundary, request_failure
from integrations.discovery import DiscoveredOperation


class MCPDispatcher:
    """Enforce exact connection grants before any remote tools/call request."""

    def __init__(self, client: Client, operations: tuple[DiscoveredOperation, ...]) -> None:
        self._client = client
        self._available = frozenset(operation.id for operation in operations if operation.unavailable_reason is None)
        self._grants: frozenset[str] = frozenset()

    def replace_operation_grants(self, grants: frozenset[str]) -> None:
        self._grants = grants

    async def dispatch(self, operation_id: str, args: dict[str, Any]) -> dict[str, Any]:
        if operation_id not in self._grants:
            raise RpcError("PERMISSION_DENIED", "This tool is not enabled for this integration.")
        if operation_id not in self._available:
            raise RpcError("NOT_FOUND", "This tool is no longer available. Reconnect to refresh tools.")
        try:
            with mcp_error_boundary():
                return await self._call(operation_id, args)
        except MCPRequestError as exc:
            raise RpcError(exc.code, f"{exc.message} {UNKNOWN_OUTCOME} omnideck has not retried it.") from exc
        except Exception as exc:
            raise RpcError("UPSTREAM", f"The remote tool did not return a confirmed result. {UNKNOWN_OUTCOME}") from exc

    async def _call(self, operation_id: str, args: dict[str, Any]) -> dict[str, Any]:
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
                raise request_failure(MCPFailure.RESULT_SIZE)
            return payload
        except TimeoutError as exc:
            raise request_failure(MCPFailure.TOOL_TIMEOUT) from exc
