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

from sdk.events import (
    AgentEvent,
    TurnEndPayload,
    publish_event,
    reset_current_conversation,
    set_current_conversation,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from sdk.context import ConversationHistory


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
    conversation: ConversationHistory | None = None,
    conversation_id: str | None = None,
) -> AsyncIterator[None]:
    """Set up and tear down per-turn state.

    Binds a stop event so ``check_stop`` works from any depth and
    registers the conversation as active. When a ``conversation`` is
    passed, the scope also binds it as the active event target and emits
    the single ``turn_end`` for the whole user turn on exit — so the
    boundary is owned here, not by the tool loop. A sub-agent's tool loop
    ending therefore can't signal that the user turn is over, and every
    entry point (chat, tasks, …) gets the boundary for free.

    The caller subscribes observers before entering and unsubscribes after
    exiting, so the final ``turn_end`` still reaches them.

    Args:
        conversation: The conversation events are published to. When None,
            no binding or ``turn_end`` happens (callers that drive the loop
            directly without an event sink, e.g. unit tests).
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
    conv_token = set_current_conversation(conversation) if conversation is not None else None
    try:
        yield None
    finally:
        if conversation is not None:
            try:
                publish_event(AgentEvent(payload=TurnEndPayload(type="turn_end")))
            except Exception:  # pragma: no cover - defensive
                logger.exception("Failed to publish turn_end for conversation '%s'", sid)
            reset_current_conversation(conv_token)
        _stop_event.reset(stop_token)
        _conversation_id.reset(conversation_token)
        _active_conversations.discard(sid)
        _active_stop_events.pop(sid, None)
