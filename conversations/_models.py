"""Models for conversation state and persistence."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ConversationResumeState(BaseModel):
    """Persisted conversation and workspace state used when resuming."""

    messages: list[dict[str, Any]]
    events: list[dict[str, Any]]
    browser_tabs: list[dict[str, Any]]
    terminal: dict[str, list[dict[str, Any]]]
    preview_state: dict[str, Any]
    profile_id: str | None


class ConversationSummary(BaseModel):
    """Summary of a conversation for listing in the UI."""

    conversation_id: str
    first_message: str = ""
    title: str = ""  # Auto-generated title (max 60 chars)
    started_at: str = ""
    turn_count: int = 0
    pinned: bool = False  # User-pinned to the top of the sidebar
    folder_id: str | None = None  # Custom folder this chat belongs to, if any


class Folder(BaseModel):
    """A user-created folder for grouping conversations in the sidebar."""

    id: str
    name: str
    icon: str = "bi-folder"  # Bootstrap icon class shown beside the folder name
    order: int = 0  # Sort position among folders (lower shows first)
    created_at: str = ""
