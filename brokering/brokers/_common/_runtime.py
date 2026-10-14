"""Shared lifecycle for native integration brokers, independent of provider auth."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any, Protocol

from brokering._control import BrokerControl, run_with_control
from brokering._session_slot import BrokerSessionSlot
from brokering._rpc import serve_rpc
from integrations.operation_grants import OperationGrants


class Dispatcher(Protocol):
    """Integration sessions expose operations and grants; LLM sessions need not."""

    def replace_operation_grants(self, grants: OperationGrants) -> None: ...

    async def dispatch(self, operation_id: str, args: dict[str, Any]) -> dict[str, Any]: ...


async def run_integration_broker(
    socket_path: Path,
    initial_connection_fields: dict[str, str],
    grants: OperationGrants,
    create_session: Callable[[dict[str, str]], AbstractAsyncContextManager[Dispatcher]],
) -> None:
    """Run integration sessions with shared startup, control, and RPC handling.

    The broker's ``create_session`` authenticates/validates connection fields,
    yields its dispatcher, and owns provider-specific cleanup. This wrapper
    adds current grants before the session can become active. The same factory
    serves startup and credential replacement, without duplicating auth logic.
    """
    @asynccontextmanager
    async def create_granted_session(connection_fields: dict[str, str]) -> AsyncIterator[Dispatcher]:
        async with create_session(connection_fields) as dispatcher:
            # Control rejects grant edits while a credential candidate is
            # pending, so this snapshot remains current through activation.
            dispatcher.replace_operation_grants(grants)
            yield dispatcher

    session_slot = BrokerSessionSlot(create_granted_session)

    def replace_grants(updated: OperationGrants) -> None:
        nonlocal grants
        grants = updated
        session_slot.current.replace_operation_grants(updated)

    async def handler(operation_id: str, args: dict[str, Any]) -> dict[str, Any]:
        # Capture one dispatcher per call: never mix accounts within an operation.
        dispatcher = session_slot.current
        return await dispatcher.dispatch(operation_id, args)

    try:
        prepared_session = await session_slot.prepare(initial_connection_fields)
        await prepared_session.activate()
        initial_connection_fields.clear()
        server = await serve_rpc(socket_path, handler)
        async with server:
            await run_with_control(server.serve_forever(), BrokerControl(replace_grants, session_slot.prepare))
    finally:
        await session_slot.close()
