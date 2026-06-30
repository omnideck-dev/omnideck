"""Conversation persistence package — store and query conversation data."""

from ._browser_tabs import BrowserTabsWriter, load_browser_tabs
from ._events_log import EventsLogWriter, load_events_jsonl
from ._models import ConversationSummary
from ._terminal import TerminalWriter, load_terminal
from ._store import (
    conversation_exists,
    delete_conversation,
    list_conversations,
    load_conversation_metadata,
    load_conversation_profile,
    load_loaded_skills,
    load_preview_state,
    mark_file_focused,
    save_conversation_pinned,
    save_conversation_profile,
    save_conversation_title,
    save_loaded_skills,
    save_preview_state,
)
from ._title_generation import generate_conversation_title

__all__ = [
    "BrowserTabsWriter",
    "ConversationSummary",
    "EventsLogWriter",
    "TerminalWriter",
    "conversation_exists",
    "delete_conversation",
    "generate_conversation_title",
    "list_conversations",
    "load_browser_tabs",
    "load_conversation_metadata",
    "load_conversation_profile",
    "load_events_jsonl",
    "load_loaded_skills",
    "load_terminal",
    "load_preview_state",
    "mark_file_focused",
    "save_conversation_pinned",
    "save_conversation_profile",
    "save_conversation_title",
    "save_loaded_skills",
    "save_preview_state",
]
