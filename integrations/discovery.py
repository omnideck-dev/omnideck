"""Validated per-connection operations; never a global dynamic tool registry."""

import json
import re
from dataclasses import dataclass
from typing import Any


_NAME = re.compile(r"^[a-zA-Z0-9_.-]{1,128}$")
MAX_OPERATIONS = 500
MAX_CATALOG_BYTES = 1024 * 1024


@dataclass(frozen=True)
class DiscoveredOperation:
    """Immutable metadata and lossless input JSON schema for one remote tool."""

    id: str
    title: str
    description: str
    schema_json: str

    def public_dict(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "description": self.description,
                "input_schema": json.loads(self.schema_json)}


def mcp_operation_id(name: str) -> str:
    if not _NAME.fullmatch(name):
        raise ValueError("The server returned an unsupported tool name.")
    return f"mcp.{name}"


def parse_discovered_operations(raw: str) -> tuple[DiscoveredOperation, ...]:
    """Validate saved/wire metadata, bounding both size and operation count."""
    if len(raw.encode()) > MAX_CATALOG_BYTES:
        raise ValueError("The server's tool catalog is too large.")
    entries = json.loads(raw)
    if not isinstance(entries, list) or len(entries) > MAX_OPERATIONS:
        raise ValueError("Invalid tool catalog.")
    result = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Invalid tool descriptor.")
        identifier, title, description, schema = (entry.get(key) for key in ("id", "title", "description", "input_schema"))
        if (
            not isinstance(identifier, str) or not identifier.startswith("mcp.")
            or identifier != mcp_operation_id(identifier[4:]) or identifier in seen
            or not isinstance(title, str) or len(title) > 256
            or not isinstance(description, str) or len(description) > 16384
            or not isinstance(schema, dict) or schema.get("type") != "object"
        ):
            raise ValueError("Invalid tool descriptor.")
        seen.add(identifier)
        result.append(DiscoveredOperation(identifier, title, description, json.dumps(schema)))
    return tuple(result)
