"""Turn lifecycle management for the agent SDK.

A *turn* is a single user message → assistant response cycle, including all
sub-agent work and tool calls that happen in between. This module provides the
async context manager that sets up and tears down everything a turn needs:

- An event dispatcher bound to a ContextVar so ``publish_event`` works
- A per-conversation stop event so ``check_stop`` / ``request_stop`` work
- Conversation liveness tracking (``is_turn_active``)
- Nudge queues live in ``_nudge_queue.py`` (leaf module, no cycles).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


logger = logging.getLogger(__name__)


class StopRequestedError(Exception):
    """Raised at safe checkpoints when the user requests a stop."""


_DEFAULT_CONVERSATION_ID = "default"

# Conversations that currently have an active turn.
_active_conversations: set[str] = set()

# Per-conversation stop events so the HTTP stop endpoint can target a specific
# conversation without interfering with others.
_active_stop_events: dict[str, asyncio.Event] = {}

# Stop event bound to the currently active turn, accessible without passing
# it through every call frame.
_stop_event: ContextVar[asyncio.Event | None] = ContextVar("turn_stop_event", default=None)

# Conversation ID for the current coroutine context, set inside turn_scope()
# and inherited by sub-agents automatically via ContextVar semantics.
_conversation_id: ContextVar[str | None] = ContextVar("turn_conversation_id", default=None)

def get_conversation_id() -> str | None:
    """Return the conversation ID for the current coroutine context, or None."""
    return _conversation_id.get()


def request_stop(conversation_id: str | None = None) -> None:
    """Signal the active turn to stop at the next safe checkpoint.

    Args:
        conversation_id: Target a specific conversation. If None, stops the default.
    """
    sid = conversation_id or _DEFAULT_CONVERSATION_ID
    event = _active_stop_events.get(sid)
    if event is not None:
        event.set()


def check_stop() -> None:
    """Raise StopRequestedError if a stop has been requested for this turn.

    Call this at safe checkpoints (e.g. top of tool loop, before each tool
    execution) to allow clean interruption without cancelling tasks mid-await.
    """
    event = _stop_event.get()
    if event is not None and event.is_set():
        raise StopRequestedError()


def is_turn_active(conversation_id: str | None = None) -> bool:
    """Return True if the given conversation has an active turn."""
    sid = conversation_id or _DEFAULT_CONVERSATION_ID
    return sid in _active_conversations


def any_turn_active() -> bool:
    """Return True if any conversation has an active turn."""
    return bool(_active_conversations)


@asynccontextmanager
async def turn_scope(
    conversation_id: str | None = None,
) -> AsyncIterator[None]:
    """Set up and tear down per-turn state.

    Binds a stop event so ``check_stop`` works from any depth and
    registers the conversation as active. Event fan-out happens via the
    bound conversation's observer list — the caller is responsible for
    subscribing observers and calling ``set_current_conversation`` before
    publishing.

    Args:
        conversation_id: Conversation identifier for per-conversation isolation.

    Yields:
        None
    """
    sid = conversation_id or _DEFAULT_CONVERSATION_ID
    stop_event = asyncio.Event()
    _active_conversations.add(sid)
    _active_stop_events[sid] = stop_event
    stop_token = _stop_event.set(stop_event)
    conversation_token = _conversation_id.set(sid)
    try:
        yield None
    finally:
        _stop_event.reset(stop_token)
        _conversation_id.reset(conversation_token)
        _active_conversations.discard(sid)
        _active_stop_events.pop(sid, None)
