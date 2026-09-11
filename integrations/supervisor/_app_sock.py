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
    field required. Label changes are meta-only; grant changes
    respawn the broker so the new env takes effect.

**reconnect** (id, auth_blob)
    Atomically replace encrypted credentials and restart the broker while
    preserving the still-available exact operation grants.

Deprecated ``permissions`` inputs and output projections remain temporarily
for the existing UI and are never used by broker authorization.

**remove** (id)
    SIGTERM the broker and delete its vault files.

The handler is a thin dispatcher: it parses args and delegates to a
:class:`BrokerManager` (lifecycle) and :class:`Registry` (read access).
"""

from __future__ import annotations

import logging
from typing import Any

from integrations._rpc import RpcError
from integrations.operation_grants import (
    OperationGrants,
    operation_grants_to_legacy_permissions,
)
from integrations.operations import operation_descriptors
from integrations.permissions import (
    Permissions,
    access_to_str,
    permissions_from_dict,
    permissions_to_dict,
)
from integrations.supervisor._manager import BrokerManager
from integrations.supervisor._registry import BrokeredConnectionRecord, Registry
from integrations.supervisor.types import IntegrationMeta

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
        if "operation_grants" in args and "permissions" in args:
            raise RpcError("BAD_REQUEST", "provide operation_grants or permissions, not both")
        operation_grants = _parse_operation_grants(args.get("operation_grants"))
        permissions = None
        if "permissions" in args:
            perms_raw = args["permissions"]
            if not isinstance(perms_raw, dict):
                raise RpcError("BAD_REQUEST", "'permissions' must be a dict")
            permissions = _parse_legacy_permissions(perms_raw)
        auth_blob = args.get("auth_blob")
        if not isinstance(auth_blob, dict):
            raise RpcError("BAD_REQUEST", "auth_blob must be a dict")
        record = await self._manager.add(
            slug=_require_str(args, "slug"),
            user_suffix=_optional_str(args, "user_suffix"),
            label=_require_str(args, "label"),
            auth_blob=auth_blob,
            operation_grants=operation_grants,
            permissions=permissions,
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
        return {
            "connections": serialized,
            # Deprecated response key retained for older client releases.
            "integrations": serialized,
        }

    def _resolve(self, args: dict[str, Any]) -> dict[str, Any]:
        integration_id = _require_str(args, "id")
        record = self._registry.get(integration_id)
        if record is None:
            raise RpcError("NOT_FOUND", f"unknown integration: {integration_id}")
        if record.state == "auth_failed":
            raise RpcError("AUTH", f"integration {integration_id!r} needs new credentials")
        if record.state != "running":
            raise RpcError("UNAVAILABLE", f"integration {integration_id!r} is not running")
        if record.broker is None:
            raise RpcError("UNAVAILABLE", f"integration {integration_id!r} has no broker")
        result: dict[str, Any] = {
            "id": record.meta.id,
            "socket": str(record.broker.socket_path),
            "kind": record.meta.kind,
        }
        if isinstance(record.meta, IntegrationMeta):
            result["operation_grants"] = sorted(record.meta.agent_operation_grants)
            result["available_operation_ids"] = sorted(record.available_operations)
            result["operations"] = operation_descriptors(record.available_operations)
            result["permissions"] = permissions_to_dict(
                operation_grants_to_legacy_permissions(
                    record.meta.agent_operation_grants,
                    record.available_operations,
                ),
            )
        return result

    async def _update(self, args: dict[str, Any]) -> dict[str, Any]:
        integration_id = _require_str(args, "id")
        if "operation_grants" in args and "permissions" in args:
            raise RpcError("BAD_REQUEST", "provide operation_grants or permissions, not both")
        operation_grants = _parse_operation_grants(args.get("operation_grants"))
        permissions = None
        if "permissions" in args:
            perms_raw = args["permissions"]
            if not isinstance(perms_raw, dict):
                raise RpcError("BAD_REQUEST", "'permissions' must be a dict")
            permissions = _parse_legacy_permissions(perms_raw)
        label: str | None = None
        if "label" in args:
            if not isinstance(args["label"], str) or not args["label"].strip():
                raise RpcError("BAD_REQUEST", "'label' must be a non-empty string")
            label = args["label"]
        if operation_grants is None and permissions is None and label is None:
            raise RpcError(
                "BAD_REQUEST",
                "update requires 'operation_grants', 'permissions', and/or 'label'",
            )
        record = await self._manager.update(
            integration_id,
            operation_grants=operation_grants,
            permissions=permissions,
            label=label,
        )
        return _record_to_dict(record)

    async def _remove(self, args: dict[str, Any]) -> dict[str, Any]:
        integration_id = _require_str(args, "id")
        await self._manager.remove(integration_id)
        return {"id": integration_id}

    async def _reconnect(self, args: dict[str, Any]) -> dict[str, Any]:
        integration_id = _require_str(args, "id")
        auth_blob = args.get("auth_blob")
        if not isinstance(auth_blob, dict):
            raise RpcError("BAD_REQUEST", "'auth_blob' must be a dict")
        record = await self._manager.reconnect(
            integration_id,
            auth_blob=auth_blob,
            kind=args.get("kind"),
        )
        return _record_to_dict(record)


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
    if isinstance(record.meta, IntegrationMeta):
        legacy = operation_grants_to_legacy_permissions(
            record.meta.agent_operation_grants,
            record.available_operations,
        )
        legacy_max = operation_grants_to_legacy_permissions(
            record.available_operations,
            record.available_operations,
        )
        result.update({
            "operation_grants": sorted(record.meta.agent_operation_grants),
            "available_operation_ids": sorted(record.available_operations),
            "operations": operation_descriptors(record.available_operations),
            # Deprecated compatibility projection for older clients.
            "permissions": permissions_to_dict(legacy),
            "max_access": {cap.value: access_to_str(access) for cap, access in legacy_max.items()},
            "capabilities": sorted(cap.value for cap in legacy_max),
        })
    return result


def _parse_operation_grants(value: Any) -> OperationGrants | None:
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise RpcError("BAD_REQUEST", "'operation_grants' must be an array of strings")
    return frozenset(value)


def _parse_legacy_permissions(value: dict[Any, Any]) -> Permissions:
    """Parse the deprecated projection without leaking ``ValueError`` as INTERNAL."""
    if any(not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()):
        raise RpcError(
            "BAD_REQUEST",
            "legacy permission names and access levels must be strings",
        )
    try:
        return permissions_from_dict(value)
    except (TypeError, ValueError) as exc:
        raise RpcError("BAD_REQUEST", f"invalid legacy permissions: {exc}") from exc


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
