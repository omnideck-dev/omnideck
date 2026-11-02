"""``app.sock`` RPC handler.

The app server (UID ``omnideck``) is the only legitimate client. Requests
and responses use the shared length-prefixed JSON framing.

Verbs
-----

**add** (slug, user_suffix, label, auth_blob, operation_grants)
    Encrypt credentials, spawn a broker, return the new record.
    Both the app-password and OAuth add flows end here.

**list** ()
    Non-secret metadata for every active integration.

**resolve** (id)
    Look up a broker's UDS path by integration ID. Called by the
    broker_client before every tool invocation.

**update** (id, operation_grants?, label?)
    Change operation grants and/or label on a live integration. At least one
    field required. Label changes are meta-only; grant changes are saved and
    sent to the running broker over its private control channel.

**reconnect** (id, auth_blob)
    Replace credentials in a healthy broker, or start one if degraded. Save
    accepted credentials and preserve exact grants regardless of scope changes.

**remove** (id)
    SIGTERM the broker and delete its vault files.

The handler is a thin dispatcher: it parses args and delegates to a
:class:`BrokerManager` (lifecycle) and :class:`Registry` (read access).
"""

from __future__ import annotations

import logging
from typing import Any

from brokering._rpc import RpcError
from brokering.connection_data import BrokerConnectionData
from integrations.operation_grants import OperationGrants
from integrations.operations import operation_descriptors
from brokering.supervisor._manager import BrokerManager
from brokering.supervisor._registry import BrokeredConnectionRecord, Registry
from brokering.supervisor.types import IntegrationConnectionMeta

logger = logging.getLogger(__name__)


class AppSockHandler:
    """Thin verb router — translates RPC frames into BrokerManager / Registry calls."""

    def __init__(
        self,
        *,
        manager: BrokerManager,
        registry: Registry,
    ) -> None:
        self._manager = manager
        self._registry = registry

    async def handle(self, verb: str, args: dict[str, Any]) -> dict[str, Any]:
        """Entry point called by the RPC layer for every incoming frame."""
        if verb == "add":
            return await self._add(args)
        if verb == "list":
            return self._list(args)
        if verb == "resolve":
            return self._resolve(args)
        if verb == "update":
            return await self._update(args)
        if verb == "reconnect":
            return await self._reconnect(args)
        if verb == "remove":
            return await self._remove(args)
        msg = f"unknown verb: {verb}"
        raise RpcError("BAD_REQUEST", msg)

    # --- verbs --------------------------------------------------------------

    async def _add(self, args: dict[str, Any]) -> dict[str, Any]:
        _reject_legacy_policy(args)
        operation_grants = _parse_operation_grants(args.get("operation_grants"))
        auth_blob = _parse_connection_data(args.get("auth_blob"))
        record = await self._manager.add(
            slug=_require_str(args, "slug"),
            user_suffix=_optional_str(args, "user_suffix"),
            label=_require_str(args, "label"),
            auth_blob=auth_blob,
            operation_grants=operation_grants,
            kind=args.get("kind"),
        )
        return _record_to_dict(record)

    def _list(self, args: dict[str, Any]) -> dict[str, Any]:
        kind = args.get("kind")
        if kind is not None and kind not in {"integration", "model_provider"}:
            raise RpcError("BAD_REQUEST", "kind must be 'integration' or 'model_provider'")
        records = [
            record for record in self._registry.list()
            if kind is None or record.meta.kind == kind
        ]
        serialized = [_record_to_dict(record) for record in records]
        return {"connections": serialized}

    def _resolve(self, args: dict[str, Any]) -> dict[str, Any]:
        connection_id = _require_str(args, "id")
        record = self._registry.get(connection_id)
        if record is None:
            raise RpcError("NOT_FOUND", f"unknown integration: {connection_id}")
        if record.state == "auth_failed":
            raise RpcError("AUTH", f"integration {connection_id!r} needs new credentials")
        if record.state != "running":
            raise RpcError("UNAVAILABLE", f"integration {connection_id!r} is not running")
        if record.broker is None:
            raise RpcError("UNAVAILABLE", f"integration {connection_id!r} has no broker")
        result: dict[str, Any] = {
            "id": record.meta.id,
            "socket": str(record.broker.socket_path),
            "kind": record.meta.kind,
        }
        if isinstance(record.meta, IntegrationConnectionMeta):
            result["operation_grants"] = sorted(record.meta.agent_operation_grants)
            result["available_operation_ids"] = sorted(record.available_operations)
            result["operations"] = operation_descriptors(record.available_operations)
        return result

    async def _update(self, args: dict[str, Any]) -> dict[str, Any]:
        connection_id = _require_str(args, "id")
        _reject_legacy_policy(args)
        operation_grants = _parse_operation_grants(args.get("operation_grants"))
        label: str | None = None
        if "label" in args:
            if not isinstance(args["label"], str) or not args["label"].strip():
                raise RpcError("BAD_REQUEST", "'label' must be a non-empty string")
            label = args["label"]
        if operation_grants is None and label is None:
            raise RpcError(
                "BAD_REQUEST",
                "update requires 'operation_grants' and/or 'label'",
            )
        record = await self._manager.update(
            connection_id,
            operation_grants=operation_grants,
            label=label,
        )
        return _record_to_dict(record)

    async def _remove(self, args: dict[str, Any]) -> dict[str, Any]:
        connection_id = _require_str(args, "id")
        await self._manager.remove(connection_id)
        return {"id": connection_id}

    async def _reconnect(self, args: dict[str, Any]) -> dict[str, Any]:
        connection_id = _require_str(args, "id")
        auth_blob = _parse_connection_data(args.get("auth_blob"))
        record = await self._manager.reconnect(
            connection_id,
            auth_blob=auth_blob,
            kind=args.get("kind"),
        )
        return _record_to_dict(record)


def _parse_connection_data(value: object) -> BrokerConnectionData:
    try:
        return BrokerConnectionData.from_wire(value)
    except ValueError as exc:
        raise RpcError("BAD_REQUEST", str(exc)) from exc


def _record_to_dict(record: BrokeredConnectionRecord) -> dict[str, Any]:
    """Wire-shape for one integration — used by ``add``, ``list``, ``update``."""
    result: dict[str, Any] = {
        "id": record.meta.id,
        "slug": record.meta.slug,
        "label": record.meta.label,
        "kind": record.meta.kind,
        "state": record.state,
        "socket": str(record.broker.socket_path) if record.broker is not None else None,
    }
    if isinstance(record.meta, IntegrationConnectionMeta):
        result.update({
            "operation_grants": sorted(record.meta.agent_operation_grants),
            "available_operation_ids": sorted(record.available_operations),
            "operations": operation_descriptors(record.available_operations),
        })
    return result


def _parse_operation_grants(value: Any) -> OperationGrants | None:
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise RpcError("BAD_REQUEST", "'operation_grants' must be an array of strings")
    return frozenset(value)


def _reject_legacy_policy(args: dict[str, Any]) -> None:
    if "permissions" in args or "write_allowed" in args:
        raise RpcError("BAD_REQUEST", "This screen is out of date. Refresh the app, then try again.")

def _optional_str(args: dict[str, Any], key: str) -> str | None:
    """Extract an optional non-empty string, accepting omission only."""
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise RpcError("BAD_REQUEST", f"{key!r} must be a non-empty string")
    return value


def _require_str(args: dict[str, Any], key: str) -> str:
    """Extract a required string arg or raise BAD_REQUEST."""
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RpcError("BAD_REQUEST", f"{key!r} required (non-empty string)")
    return value
