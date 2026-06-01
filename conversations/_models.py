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
