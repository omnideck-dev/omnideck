"""Shared authorization-aware dispatch for integration brokers.

Every broker must enforce the connection's exact operation grants at its RPC
boundary. Keeping that gate here prevents individual brokers from drifting in
how they authorize operations or report missing handlers.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from integrations._rpc import RpcError
from integrations.operation_grants import OperationGrants
from integrations.operations import OPERATIONS_BY_ID

OperationHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


async def dispatch_granted_operation(
    operation_id: str,
    args: dict[str, Any],
    *,
    operation_grants: OperationGrants,
    handlers: Mapping[str, OperationHandler],
) -> dict[str, Any]:
    """Validate, authorize, and invoke one canonical broker operation.

    The ordering is deliberate: validate the canonical operation, enforce the
    grant, and only then inspect implementation details. A caller without a
    grant therefore cannot use handler availability as an information oracle.
    """
    if operation_id not in OPERATIONS_BY_ID:
        raise RpcError("BAD_REQUEST", f"unknown operation: {operation_id}")

    if operation_id not in operation_grants:
        raise RpcError(
            "PERMISSION_DENIED",
            f"operation {operation_id!r} is not granted for this integration",
        )

    handler = handlers.get(operation_id)
    if handler is None:
        raise RpcError("BAD_REQUEST", f"operation not implemented: {operation_id}")
    return await handler(args)


__all__ = ["OperationHandler", "dispatch_granted_operation"]
