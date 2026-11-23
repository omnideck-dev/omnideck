"""Reconnect failed MCP transports while preserving the outcome of each tool invocation."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from brokering._control import CredentialRejected
from brokering._rpc import RpcError
from brokering._session_slot import BrokerSessionSlot
from brokering.mcp_protocol import MCPRequestError, connect, discover
from .client import MCPDispatcher


@dataclass
class _Transport:
    dispatcher: MCPDispatcher
    disconnected: asyncio.Event


class _Session:
    def __init__(self, fields: dict[str, str]) -> None:
        self._fields = fields.copy()
        self._grants: frozenset[str] = frozenset()
        self._replacement = asyncio.Lock()
        self._transports = BrokerSessionSlot(self._open_transport)

    @asynccontextmanager
    async def _open_transport(self, fields: dict[str, str]) -> AsyncIterator[_Transport]:
        disconnected = asyncio.Event()
        async with connect(fields["MCP_ENDPOINT"], token=fields["MCP_ACCESS_TOKEN"], disconnected=disconnected) as client:
            dispatcher = MCPDispatcher(client, await discover(client))
            dispatcher.replace_operation_grants(self._grants)
            yield _Transport(dispatcher, disconnected)

    async def open(self) -> None:
        prepared = await self._transports.prepare(self._fields)
        await prepared.activate()

    async def close(self) -> None:
        await self._transports.close()

    def replace_operation_grants(self, grants: frozenset[str]) -> None:
        self._grants = grants
        self._transports.current.dispatcher.replace_operation_grants(grants)

    async def dispatch(self, operation_id: str, args: dict[str, Any]) -> dict[str, Any]:
        if self._transports.current.disconnected.is_set():
            self._transports.current.dispatcher.require_grant(operation_id)
            try:
                async with asyncio.timeout(30), self._replacement:
                    if self._transports.current.disconnected.is_set():
                        await self.open()
            except MCPRequestError as exc:
                raise RpcError(exc.code, f"{exc.message} The tool was not invoked.") from exc
            except Exception as exc:
                raise RpcError("UNAVAILABLE", "Could not reconnect to the MCP server. The tool was not invoked.") from exc
        async with self._transports.borrow() as transport:
            try:
                return await transport.dispatcher.dispatch(operation_id, args)
            except RpcError as exc:
                if exc.code == "UPSTREAM":
                    transport.disconnected.set()
                raise


@asynccontextmanager
async def create_session(fields: dict[str, str]) -> AsyncIterator[_Session]:
    session = _Session(fields)
    try:
        try:
            await session.open()
        except MCPRequestError as exc:
            if exc.code == "AUTH":
                raise CredentialRejected("AUTH") from exc
            raise
        yield session
    finally:
        await session.close()
