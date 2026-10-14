"""Exact operation-grant validation and broker environment serialization."""

from __future__ import annotations

import json
from collections.abc import Iterable

OperationGrants = frozenset[str]


def normalize_operation_grants(
    requested: Iterable[str],
    available_operations: Iterable[str],
) -> OperationGrants:
    """Return only valid, currently available canonical operation IDs."""
    available = frozenset(available_operations)
    return frozenset(
        operation_id for operation_id in requested if isinstance(operation_id, str) and operation_id in available
    )


def operation_grants_to_env(grants: Iterable[str]) -> str:
    """Serialize exact grants for the supervisor-to-broker environment."""
    return json.dumps(sorted(set(grants)), separators=(",", ":"))


def operation_grants_from_env(raw: str) -> OperationGrants:
    """Parse and validate exact grants from a broker environment value."""
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("OPERATION_GRANTS must be a JSON array") from exc
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("OPERATION_GRANTS must be a JSON array of strings")
    return frozenset(value)


__all__ = [
    "OperationGrants",
    "normalize_operation_grants",
    "operation_grants_from_env",
    "operation_grants_to_env",
]
