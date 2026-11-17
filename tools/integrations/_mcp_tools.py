"""Connection-bound LLM adapters for explicitly selected remote operations."""

import hashlib
import json
import re
from typing import Any

from agent_core.tools import SchemaTool
from integrations.connection_cache import IntegrationConnection
from integrations.discovery import DiscoveredOperation
from integrations.service import integration_service


def build_mcp_tool(connection: IntegrationConnection, operation: DiscoveredOperation) -> SchemaTool:
    """Preserve upstream inputs without adding routing arguments to their schema."""
    # Tool names have provider-specific length/character limits. A stable digest
    # disambiguates both duplicate remote names and sanitized/truncated names.
    identity = f"{connection.id}\0{operation.id}"
    suffix = hashlib.sha256(identity.encode()).hexdigest()[:16]
    readable = re.sub(r"[^a-zA-Z0-9_-]", "_", operation.id[4:])[:42]
    name = f"mcp_{readable}_{suffix}"

    async def invoke(arguments: dict[str, Any]) -> Any:
        return await integration_service.invoke(connection.id, operation.id, arguments)

    return SchemaTool(
        name, f"{operation.title} ({connection.label or connection.slug}).\n{operation.description}",
        json.loads(operation.schema_json), invoke,
    )
