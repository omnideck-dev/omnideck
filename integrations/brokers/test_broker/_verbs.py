"""Minimal stateful operation dispatcher for the development test broker."""

from __future__ import annotations

from typing import Any

from integrations._rpc import RpcError
from integrations.brokers._common._dispatch import (
    OperationHandler,
    dispatch_granted_operation,
)
from integrations.operation_grants import OperationGrants


class VerbDispatcher:
    """Serve two independent operations over the normal broker RPC boundary."""

    def __init__(self, *, operation_grants: OperationGrants, initial_value: str) -> None:
        self._operation_grants = operation_grants
        self._value = initial_value
        self._handlers: dict[str, OperationHandler] = {
            "test.value.get": self._get_value,
            "test.value.set": self._set_value,
        }

    async def dispatch(self, operation_id: str, args: dict[str, Any]) -> dict[str, Any]:
        return await dispatch_granted_operation(
            operation_id,
            args,
            operation_grants=self._operation_grants,
            handlers=self._handlers,
        )

    async def _get_value(self, _args: dict[str, Any]) -> dict[str, Any]:
        return {"value": self._value}

    async def _set_value(self, args: dict[str, Any]) -> dict[str, Any]:
        value = args.get("value")
        if not isinstance(value, str) or not value:
            raise RpcError("BAD_REQUEST", "'value' required (non-empty string)")
        self._value = value
        return {"value": self._value}


__all__ = ["VerbDispatcher"]
