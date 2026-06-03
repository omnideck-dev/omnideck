"""Resolve an integration capability to the tool callables it currently backs.

One place owns the mapping from a capability to its tools, and the access
thresholds that gate them, so that wiring isn't duplicated wherever integration
tools are assembled.

Read tools are offered at ``Access.READ``; write tools only at
``Access.READ_WRITE``. A capability that no running integration provides at the
required access resolves to an empty list.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any

from integrations.permissions import Access, Capability
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


def _ids_with_access(
    integrations: Iterable[RegisteredIntegration],
    cap: Capability,
    min_access: Access,
) -> frozenset[str]:
    """Integration IDs that grant at least ``min_access`` for ``cap``.

    Two ways to be excluded: the integration isn't running (a dead or auth-failed
    broker is skipped so the agent never calls into one that can't answer), or it
    doesn't grant enough access — an integration that doesn't list ``cap`` at all
    counts as ``Access.OFF``.
    """
    return frozenset(
        integration.id
        for integration in integrations
        if integration.state == "running"
        and integration.permissions.get(cap, Access.OFF) >= min_access
    )


def integration_tools_for(
    capability: Capability,
    integrations: Iterable[RegisteredIntegration],
) -> list[Callable[..., Any]]:
    """Tool callables for ``capability`` given the current ``integrations``.

    Each access tier's builders are bound to the integration ids that meet that
    tier — READ tools cover every integration with at least read access, and
    READ_WRITE tools only the ones that also grant writes. A capability no
    running integration provides at the required access yields an empty list.
    """
    tiers = _BUILDERS.get(capability)
    if tiers is None:
        return []
    # _ids_with_access consumes the integrations once per tier, so materialize.
    integrations = list(integrations)
    tools: list[Callable[..., Any]] = []
    # Build each tier's tools against the ids that clear that tier's access bar.
    for access, builders in tiers.items():
        ids = _ids_with_access(integrations, capability, access)
        if ids:
            tools.extend(build(ids) for build in builders)
    return tools


async def all_integration_tools() -> list[Callable[..., Any]]:
    """Every integration tool the currently registered integrations back.

    The union of :func:`integration_tools_for` across all capabilities. Awaits
    the integrations cache itself, so a caller that just wants every integration
    tool doesn't have to know how integrations are fetched.
    """
    # Resolved at call time so the cache accessor is looked up fresh, not bound
    # at import — keeps the patch point at ``tools.integrations`` intact.
    from tools.integrations import registered_integrations

    integrations = list((await registered_integrations()).values())
    tools: list[Callable[..., Any]] = []
    for capability in _BUILDERS:
        tools.extend(integration_tools_for(capability, integrations))
    return tools
