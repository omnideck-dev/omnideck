"""Project explicitly granted integration operations into agent tools."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from integrations.connection_cache import ConnectionSnapshot, IntegrationConnection
from tools.integrations.contacts.list_contacts import build_list_contacts_tool
from tools.integrations.contacts.search_contacts import build_search_contacts_tool
from tools.integrations.create_event import build_create_event_tool
from tools.integrations.delete_event import build_delete_event_tool
from tools.integrations.delete_event_series import build_delete_event_series_tool
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
from tools.integrations.search_events import build_search_events_tool
from tools.integrations.send_email import build_send_email_tool
from tools.integrations.update_event import build_update_event_tool
from tools.integrations.update_event_series import build_update_event_series_tool

ToolBuilder = Callable[[Iterable[str]], Callable[..., Any]]

_BUILDERS: dict[str, ToolBuilder] = {
    "email.mailboxes.list": build_list_email_folders_tool,
    "email.messages.list": build_list_email_messages_tool,
    "email.messages.get": build_read_email_message_tool,
    "email.messages.search": build_search_email_tool,
    "email.attachments.download": build_download_email_attachment_tool,
    "email.messages.move": build_move_email_tool,
    "email.messages.send": build_send_email_tool,
    "calendar.calendars.list": build_list_calendars_tool,
    "calendar.events.list": build_list_events_tool,
    "calendar.events.search": build_search_events_tool,
    "calendar.events.create": build_create_event_tool,
    "calendar.events.update": build_update_event_tool,
    "calendar.events.delete": build_delete_event_tool,
    "calendar.series.update": build_update_event_series_tool,
    "calendar.series.delete": build_delete_event_series_tool,
    "drive.files.list": build_list_drive_files_tool,
    "drive.files.search": build_search_drive_files_tool,
    "drive.files.get_metadata": build_get_drive_file_metadata_tool,
    "drive.files.export": build_export_drive_file_tool,
    "drive.files.upload": build_upload_drive_file_tool,
    "drive.folders.create": build_create_drive_folder_tool,
    "drive.files.update": build_update_drive_file_tool,
    "drive.files.trash": build_trash_drive_file_tool,
    "drive.files.share": build_share_drive_file_tool,
    "contacts.people.list": build_list_contacts_tool,
    "contacts.people.search": build_search_contacts_tool,
    "http.request": build_call_api_tool,
}


@dataclass(frozen=True)
class OperationTools:
    """Agent tools currently granted in one user-facing category."""

    tools: list[Callable[..., Any]]
    available: bool


def _ids_granting(
    operation_id: str,
    connections: Iterable[IntegrationConnection],
) -> frozenset[str]:
    return frozenset(
        connection.id
        for connection in connections
        if connection.kind == "integration"
        and connection.state == "running"
        and operation_id in connection.operation_grants
    )


def _tools_for_category(
    category: str,
    connections: Iterable[IntegrationConnection],
) -> list[Callable[..., Any]]:
    connections = list(connections)
    tools: list[Callable[..., Any]] = []
    prefix = f"{category}."
    for operation_id, builder in _BUILDERS.items():
        if not operation_id.startswith(prefix):
            continue
        ids = _ids_granting(operation_id, connections)
        if ids:
            tools.append(builder(ids))
    return tools


def integration_tools_by_category(connections: ConnectionSnapshot = ()) -> dict[str, OperationTools]:
    categories = {operation_id.split(".", 1)[0] for operation_id in _BUILDERS}
    result: dict[str, OperationTools] = {}
    for category in categories:
        tools = _tools_for_category(category, connections)
        result[category] = OperationTools(tools=tools, available=bool(tools))
    return result


__all__ = ["OperationTools", "integration_tools_by_category"]
