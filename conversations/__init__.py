"""Conversation persistence package — store and query conversation data."""

from ._browser_tabs import BrowserTabsWriter, load_browser_tabs
from ._events_log import EventsLogWriter, load_events_jsonl
from ._folders import (
    create_folder,
    delete_folder,
    folder_exists,
    list_folders,
    update_folder,
)
from ._models import ConversationSummary, Folder
from ._terminal import TerminalWriter, load_terminal
from ._store import (
    archive_conversation,
    clear_folder_from_conversations,
    conversation_exists,
    delete_conversation,
    list_archived_conversations,
    list_conversations,
    load_conversation_metadata,
    load_conversation_profile,
    load_loaded_skills,
    load_preview_state,
    save_conversation_folder,
    save_conversation_pinned,
    save_conversation_profile,
    save_conversation_title,
    save_loaded_skills,
    save_preview_state,
    unarchive_conversation,
)
from ._title_generation import generate_conversation_title

__all__ = [
    "BrowserTabsWriter",
    "ConversationSummary",
    "EventsLogWriter",
    "Folder",
    "TerminalWriter",
    "archive_conversation",
    "clear_folder_from_conversations",
    "conversation_exists",
    "create_folder",
    "delete_conversation",
    "delete_folder",
    "folder_exists",
    "generate_conversation_title",
    "list_archived_conversations",
    "list_conversations",
    "list_folders",
    "load_browser_tabs",
    "load_conversation_metadata",
    "load_conversation_profile",
    "load_events_jsonl",
    "load_loaded_skills",
    "load_terminal",
    "load_preview_state",
    "save_conversation_folder",
    "save_conversation_pinned",
    "save_conversation_profile",
    "save_conversation_title",
    "save_loaded_skills",
    "save_preview_state",
    "unarchive_conversation",
    "update_folder",
]
