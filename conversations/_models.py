"""Pydantic models for conversation persistence."""

from __future__ import annotations

from pydantic import BaseModel


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
    color: str = ""  # Hex accent used for the folder's dot in the sidebar
    order: int = 0  # Sort position among folders (lower shows first)
    created_at: str = ""
