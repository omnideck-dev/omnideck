"""Conversation persistence package — store and query conversation data."""

from ._events_log import EventsLogWriter, load_events_jsonl
from ._models import ConversationSummary
from ._store import (
    conversation_exists,
    delete_conversation,
    list_conversations,
    load_conversation_metadata,
    load_conversation_profile,
    load_loaded_skills,
    load_preview_state,
    save_conversation_pinned,
    save_conversation_profile,
    save_conversation_title,
    save_loaded_skills,
    save_preview_state,
)
from ._title_generation import generate_conversation_title

__all__ = [
    "ConversationSummary",
    "EventsLogWriter",
    "conversation_exists",
    "delete_conversation",
    "generate_conversation_title",
    "list_conversations",
    "load_conversation_metadata",
    "load_conversation_profile",
    "load_events_jsonl",
    "load_loaded_skills",
    "load_preview_state",
    "save_conversation_pinned",
    "save_conversation_profile",
    "save_conversation_title",
    "save_loaded_skills",
    "save_preview_state",
]
