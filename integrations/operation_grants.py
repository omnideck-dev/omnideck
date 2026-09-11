"""Operation-grant serialization and legacy permission compatibility.

Read/write capability tiers are intentionally confined to this compatibility
module.  Version-3 metadata and brokers only persist or consume canonical
operation IDs.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

from integrations.permissions import Access, Capability, Permissions

OperationGrants = frozenset[str]

_LEGACY_READ: dict[Capability, frozenset[str]] = {
    Capability.EMAIL: frozenset(
        {
            "email.mailboxes.list",
            "email.messages.list",
            "email.messages.search",
            "email.messages.get",
            "email.attachments.download",
        }
    ),
    Capability.CALENDAR: frozenset(
        {
            "calendar.calendars.list",
            "calendar.events.list",
            "calendar.events.search",
        }
    ),
    Capability.DRIVE: frozenset(
        {
            "drive.files.list",
            "drive.files.search",
            "drive.files.get_metadata",
            "drive.files.export",
        }
    ),
    Capability.CONTACTS: frozenset({"contacts.people.list", "contacts.people.search"}),
    # A generic request cannot honestly be represented as read-only.  Legacy
    # http:r therefore migrates to no grant instead of widening authority.
    Capability.HTTP: frozenset(),
}

_LEGACY_WRITE: dict[Capability, frozenset[str]] = {
    Capability.EMAIL: frozenset({"email.messages.move", "email.messages.send"}),
    Capability.CALENDAR: frozenset(
        {
            "calendar.events.create",
            "calendar.events.update",
            "calendar.events.delete",
            "calendar.series.update",
            "calendar.series.delete",
        }
    ),
    Capability.DRIVE: frozenset(
        {
            "drive.files.upload",
            "drive.folders.create",
            "drive.files.update",
            "drive.files.trash",
            "drive.files.share",
        }
    ),
    Capability.CONTACTS: frozenset(),
    Capability.HTTP: frozenset({"http.request"}),
}


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


def legacy_permissions_to_operation_grants(
    permissions: Permissions,
    available_operations: Iterable[str],
) -> OperationGrants:
    """Expand a v2 permission selection through the frozen migration table."""
    grants: set[str] = set()
    for capability, access in permissions.items():
        if access >= Access.READ:
            grants.update(_LEGACY_READ.get(capability, ()))
        if access >= Access.READ_WRITE:
            grants.update(_LEGACY_WRITE.get(capability, ()))
    return normalize_operation_grants(grants, available_operations)


def operation_grants_to_legacy_permissions(
    grants: Iterable[str],
    available_operations: Iterable[str],
) -> Permissions:
    """Conservatively project exact grants to the old UI's off/r/rw shape.

    A custom subset projects to OFF.  It must never project to a broader tier
    because an old client could write that projection back and widen access.
    """
    selected = frozenset(grants)
    available = frozenset(available_operations)
    result: Permissions = {}
    for capability in (Capability.EMAIL, Capability.CALENDAR, Capability.DRIVE, Capability.CONTACTS, Capability.HTTP):
        readable = _LEGACY_READ[capability] & available
        writable = _LEGACY_WRITE[capability] & available
        relevant = readable | writable
        if not relevant:
            continue
        chosen = selected & relevant
        if chosen == relevant and writable:
            result[capability] = Access.READ_WRITE
        elif chosen == readable and readable:
            result[capability] = Access.READ
        else:
            result[capability] = Access.OFF
    return result


def legacy_v1_to_operation_grants(
    *,
    write_allowed: bool,
    available_operations: Iterable[str],
) -> OperationGrants:
    """Expand the original global write flag without retaining it in v3."""
    access = Access.READ_WRITE if write_allowed else Access.READ
    permissions = {
        capability: access
        for capability in (
            Capability.EMAIL,
            Capability.CALENDAR,
            Capability.DRIVE,
            Capability.CONTACTS,
            Capability.HTTP,
        )
    }
    return legacy_permissions_to_operation_grants(permissions, available_operations)


__all__ = [
    "OperationGrants",
    "legacy_permissions_to_operation_grants",
    "legacy_v1_to_operation_grants",
    "normalize_operation_grants",
    "operation_grants_from_env",
    "operation_grants_to_env",
    "operation_grants_to_legacy_permissions",
]
