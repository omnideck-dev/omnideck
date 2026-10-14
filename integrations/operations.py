"""Canonical application operations exposed by native integrations.

An operation is the stable contract shared by the integration service, broker
authorization, agent adapters, and a future Custom App SDK. The same operation
ID is used for invocation, broker dispatch, and persisted grants. LLM-facing
tool names remain presentation details.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IntegrationOperation:
    """Identity and display metadata for one structured operation."""

    id: str
    title: str
    description: str

    def public_dict(self) -> dict[str, Any]:
        """Return the safe descriptor sent to application consumers."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
        }


def _operation(
    id_: str,
    title: str,
    description: str,
) -> IntegrationOperation:
    return IntegrationOperation(
        id=id_,
        title=title,
        description=description,
    )


NATIVE_OPERATIONS: tuple[IntegrationOperation, ...] = (
    # Email
    _operation("email.mailboxes.list", "List email folders", "List the folders in an email account."),
    _operation("email.messages.list", "List email messages", "List recent messages in a folder."),
    _operation("email.messages.search", "Search email", "Search messages in a folder."),
    _operation(
        "email.messages.get",
        "Read email message",
        "Read one email message and its attachment metadata.",
    ),
    _operation(
        "email.attachments.download",
        "Download email attachment",
        "Download one attachment to omnideck's downloads directory.",
    ),
    _operation("email.messages.move", "Move email messages", "Move messages between folders."),
    _operation("email.messages.send", "Send email", "Send an email message through the connected account."),
    # Calendar
    _operation("calendar.calendars.list", "List calendars", "List calendars in an account."),
    _operation("calendar.events.list", "List calendar events", "List events in a time window."),
    _operation(
        "calendar.events.search",
        "Search calendar events",
        "Search calendar events by text and time window.",
    ),
    _operation("calendar.events.create", "Create calendar event", "Create an event in a calendar."),
    _operation("calendar.events.update", "Update calendar event", "Update one event occurrence."),
    _operation("calendar.events.delete", "Delete calendar event", "Delete one event occurrence."),
    _operation(
        "calendar.series.update",
        "Update calendar series",
        "Update an entire recurring event series.",
    ),
    _operation(
        "calendar.series.delete",
        "Delete calendar series",
        "Delete an entire recurring event series.",
    ),
    # Drive
    _operation("drive.files.list", "List Drive files", "List files in a Drive folder."),
    _operation("drive.files.search", "Search Drive files", "Search Drive files by text."),
    _operation(
        "drive.files.get_metadata",
        "Get Drive file metadata",
        "Get metadata for one Drive file.",
    ),
    _operation(
        "drive.files.export",
        "Export Drive file",
        "Export a Drive file to the downloads directory.",
    ),
    _operation("drive.files.upload", "Upload Drive file", "Upload a new file to Drive."),
    _operation("drive.folders.create", "Create Drive folder", "Create a folder in Drive."),
    _operation(
        "drive.files.update",
        "Update Drive file",
        "Rename or replace the contents of a Drive file.",
    ),
    _operation("drive.files.trash", "Trash Drive file", "Move a Drive file to trash."),
    _operation("drive.files.share", "Share Drive file", "Change sharing access for a Drive file."),
    # Contacts
    _operation("contacts.people.list", "List contacts", "List people in the connected contacts account."),
    _operation(
        "contacts.people.search",
        "Search contacts",
        "Search people in the connected contacts account.",
    ),
    # Generic HTTP is intentionally one indivisible operation.
    _operation(
        "http.request",
        "Call API",
        "Make an authenticated HTTP request against the configured base URL.",
    ),
    # Development-only fake integration. Its catalog entry is gated, while
    # these stable descriptors remain registered so every normal invocation
    # boundary (service -> broker client -> broker) is exercised in E2E.
    _operation("test.value.get", "Get test value", "Read the value held by the test integration."),
    _operation("test.value.set", "Set test value", "Change the value held by the test integration."),
)

OPERATIONS_BY_ID: dict[str, IntegrationOperation] = {operation.id: operation for operation in NATIVE_OPERATIONS}


def operation_for_id(operation_id: str) -> IntegrationOperation | None:
    """Return the registered operation for a canonical ID, if present."""
    return OPERATIONS_BY_ID.get(operation_id)


def operation_descriptors(operation_ids: set[str] | frozenset[str]) -> list[dict[str, Any]]:
    """Serialize known operations in stable ID order."""
    return [
        OPERATIONS_BY_ID[operation_id].public_dict()
        for operation_id in sorted(operation_ids)
        if operation_id in OPERATIONS_BY_ID
    ]


OPERATIONS_BY_GROUP: dict[str, frozenset[str]] = {
    namespace: frozenset(operation.id for operation in NATIVE_OPERATIONS if operation.id.startswith(f"{namespace}."))
    for namespace in ("email", "calendar", "drive", "contacts", "http", "test")
}

__all__ = [
    "IntegrationOperation",
    "NATIVE_OPERATIONS",
    "OPERATIONS_BY_GROUP",
    "OPERATIONS_BY_ID",
    "operation_descriptors",
    "operation_for_id",
]
