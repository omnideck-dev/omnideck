"""Resolve integration capabilities to the tool callables they currently back.

One place owns the mapping from a capability to its tools, the access thresholds
that gate them, and whether a running integration provides it — so that wiring
isn't duplicated wherever integration tools are assembled.

Read tools are offered at ``Access.READ``; write tools only at
``Access.READ_WRITE``. A capability that no running integration provides at the
required access resolves to an empty list.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from integrations.permissions import Access, Capability
from tools.integrations._state import registered_integrations
from tools.integrations.contacts.list_contacts import build_list_contacts_tool
from tools.integrations.contacts.search_contacts import build_search_contacts_tool
from tools.integrations.create_event import build_create_event_tool
from tools.integrations.delete_event import build_delete_event_tool
from tools.integrations.download_email_attachment import build_download_email_attachment_tool
from tools.integrations.drive.create_folder import build_create_drive_folder_tool
from tools.integrations.drive.export_file import build_export_drive_file_tool
from tools.integrations.drive.get_file_metadata import build_get_drive_file_metadata_tool
from tools.integrations.drive.list_files import build_list_drive_files_tool
from tools.integrations.drive.search_files import build_search_drive_files_tool
from tools.integrations.drive.share_file import build_share_drive_file_tool
from tools.integrations.drive.trash_file import build_trash_drive_file_tool
from tools.integrations.drive.update_file import build_update_drive_file_tool
from tools.integrations.drive.upload_file import build_upload_drive_file_tool
from tools.integrations.http.call_api import build_call_api_tool
from tools.integrations.list_calendars import build_list_calendars_tool
from tools.integrations.list_email_folders import build_list_email_folders_tool
from tools.integrations.list_email_messages import build_list_email_messages_tool
from tools.integrations.list_events import build_list_events_tool
from tools.integrations.move_email import build_move_email_tool
from tools.integrations.read_email_message import build_read_email_message_tool
from tools.integrations.search_email import build_search_email_tool
from tools.integrations.send_email import build_send_email_tool
from tools.integrations.update_event import build_update_event_tool

if TYPE_CHECKING:
    from tools.integrations.types import RegisteredIntegration

# A builder takes the integration ids that currently satisfy an access tier and
# returns one tool bound to them. It's a factory, not the tool itself, because
# the tool's docstring advertises those exact ids to the model — so it has to be
# rebuilt each time the set of connected integrations might have changed.
ToolBuilder = Callable[[Iterable[str]], Callable[..., Any]]

# capability -> {minimum access a tool needs -> builders unlocked at that access}.
# Keying on Access makes the tier explicit and lets the resolver treat every
# capability uniformly — a read-only capability just omits the READ_WRITE entry.
# The generic call_api tool is the whole HTTP tier: the broker promotes its
# per-call access check to read_write when the method mutates, so one tool
# offered at READ covers both.
_BUILDERS: dict[Capability, dict[Access, list[ToolBuilder]]] = {
    Capability.EMAIL: {
        Access.READ: [
            build_list_email_folders_tool,
            build_list_email_messages_tool,
            build_read_email_message_tool,
            build_search_email_tool,
            build_download_email_attachment_tool,
        ],
        Access.READ_WRITE: [build_move_email_tool, build_send_email_tool],
    },
    Capability.CALENDAR: {
        Access.READ: [build_list_calendars_tool, build_list_events_tool],
        Access.READ_WRITE: [build_create_event_tool, build_update_event_tool, build_delete_event_tool],
    },
    Capability.DRIVE: {
        Access.READ: [
            build_list_drive_files_tool,
            build_search_drive_files_tool,
            build_get_drive_file_metadata_tool,
            build_export_drive_file_tool,
        ],
        Access.READ_WRITE: [
            build_upload_drive_file_tool,
            build_create_drive_folder_tool,
            build_update_drive_file_tool,
            build_trash_drive_file_tool,
            build_share_drive_file_tool,
        ],
    },
    Capability.CONTACTS: {Access.READ: [build_list_contacts_tool, build_search_contacts_tool]},
    Capability.HTTP: {Access.READ: [build_call_api_tool]},
}


@dataclass(frozen=True)
class CapabilityTools:
    """A capability's current tools, and whether a connected integration makes it available."""

    tools: list[Callable[..., Any]]
    available: bool


def _ids_granting(
    capability: Capability,
    integrations: Iterable[RegisteredIntegration],
    min_access: Access,
) -> frozenset[str]:
    """The ids of integrations that grant ``capability`` at ``min_access`` or above.

    This id set is what a tool gets *scoped to* — a tool is built bound to the exact
    integrations it's allowed to act on (see ``ToolBuilder`` above), so it has to know
    which ids qualify. An integration is left out if it isn't running (a dead or
    auth-failed broker, so the agent never calls one that can't answer) or grants too
    little access — one that doesn't list ``capability`` counts as ``Access.OFF``.
    ``Access`` is ordered, so ``>=`` reads as "this tier or higher".
    """
    return frozenset(
        integration.id
        for integration in integrations
        if integration.state == "running"
        and integration.permissions.get(capability, Access.OFF) >= min_access
    )


def _capability_available(
    capability: Capability,
    integrations: Iterable[RegisteredIntegration],
) -> bool:
    """Whether a connected integration makes ``capability`` available (at least read access).

    A capability isn't itself connected — an integration is, and a connected one
    makes its capabilities available. This is the catalog's signal that the category
    is usable: read straight from the integrations, not inferred from how many tools
    resolved.
    """
    return bool(_ids_granting(capability, integrations, Access.READ))


def _tools_for_capability(
    capability: Capability,
    integrations: Iterable[RegisteredIntegration],
) -> list[Callable[..., Any]]:
    """The tools for ``capability``, each scoped to the integrations that may run it.

    Walk the capability's access tiers; for each, build that tier's tools bound to the
    ids that clear the tier. So read tools cover every integration with at least read
    access, write tools only those that also grant writes — and one integration can
    appear in both a read tool and a write tool.

    Example — EMAIL with two Gmail accounts, A (read+write) and B (read-only)::

        READ tier        ids {A, B}   ->  search_email / list_messages over both
        READ_WRITE tier  ids {A}      ->  send_email / move_email over A only

    A capability no running integration provides at any tier yields no tools.
    """
    tiers = _BUILDERS.get(capability)
    if tiers is None:
        return []
    # _ids_granting re-scans the integrations once per tier, so materialize the list.
    integrations = list(integrations)
    tools: list[Callable[..., Any]] = []
    for access, builders in tiers.items():
        ids = _ids_granting(capability, integrations, access)
        if ids:
            tools.extend(build(ids) for build in builders)
    return tools


async def integration_tools_by_capability() -> dict[Capability, CapabilityTools]:
    """Snapshot the registry and resolve every backed capability to its tools.

    One registry read covers all capabilities, so a caller assembling the full
    catalog never has to touch the integration registry itself.
    """
    integrations = list((await registered_integrations()).values())
    by_capability: dict[Capability, CapabilityTools] = {}
    for capability in _BUILDERS:
        tools = _tools_for_capability(capability, integrations)
        available = _capability_available(capability, integrations)
        by_capability[capability] = CapabilityTools(tools=tools, available=available)
    return by_capability


__all__ = [
    "CapabilityTools",
    "integration_tools_by_capability",
]
