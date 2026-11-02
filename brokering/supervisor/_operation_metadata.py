"""Bind non-secret discovery metadata to the credentials used to discover it."""

import hashlib
import json

from brokering.catalog import CatalogEntry
from brokering.connection_data import BrokerConnectionData
from integrations.discovery import DiscoveredOperation


def catalog_digest(operations: tuple[DiscoveredOperation, ...]) -> str:
    catalog = json.dumps([operation.public_dict() for operation in operations], sort_keys=True, allow_nan=False)
    return hashlib.sha256(catalog.encode()).hexdigest()


def bind_mcp_catalog(
    fields: BrokerConnectionData, operations: tuple[DiscoveredOperation, ...],
) -> BrokerConnectionData:
    """Store only a consistency checksum with secrets, never tool definitions."""
    if "discovered_operations" in fields:
        raise ValueError("Discovered tools must be supplied as connection metadata")
    return BrokerConnectionData({**fields, "discovered_operations_digest": catalog_digest(operations)})


def connection_operations(
    entry: CatalogEntry, fields: BrokerConnectionData, operations: tuple[DiscoveredOperation, ...],
) -> frozenset[str]:
    if entry.driver_id != "remote.mcp":
        if operations:
            raise ValueError("Native connections cannot supply a discovered catalog")
        return entry.resolve_operations(fields.granted_scopes)
    if "discovered_operations" in fields or fields.get("discovered_operations_digest") != catalog_digest(operations):
        raise ValueError("Saved tool catalog does not match credentials; reconnect required")
    return frozenset(operation.id for operation in operations if operation.unavailable_reason is None)
