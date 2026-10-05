"""Project encrypted connection discovery into non-secret runtime metadata."""

from brokering.catalog import CatalogEntry
from brokering.connection_data import BrokerConnectionData
from integrations.discovery import DiscoveredOperation, parse_discovered_operations


def connection_operations(
    entry: CatalogEntry, fields: BrokerConnectionData,
) -> tuple[frozenset[str], tuple[DiscoveredOperation, ...]]:
    if entry.driver_id != "remote.mcp":
        return entry.resolve_operations(fields.granted_scopes), ()
    operations = parse_discovered_operations(fields.get("discovered_operations", "[]"))
    return frozenset(operation.id for operation in operations), operations
