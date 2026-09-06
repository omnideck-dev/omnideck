"""Scoped conversation binding and cooperative stop checks for SDK callers.

Run admission, liveness, remote controls, and terminal events belong to the
application runtime. This module only binds caller-supplied execution inputs.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar

from sdk.control import ExecutionControl, _current_control
from sdk.events import reset_current_conversation, set_current_conversation
from sdk.events._context import EventSink

_conversation_id: ContextVar[str | None] = ContextVar("turn_conversation_id", default=None)


def get_conversation_id() -> str | None:
    return _conversation_id.get()


def check_stop() -> None:
    control = _current_control.get()
    if control is not None:
        control.check_stop()


@asynccontextmanager
async def turn_scope(
    conversation: EventSink | None = None,
    conversation_id: str | None = None,
    stop_event: asyncio.Event | None = None,
) -> AsyncIterator[None]:
    """Bind a conversation and stop signal without owning a run or its events."""
    control = ExecutionControl(stop_event if stop_event is not None else asyncio.Event())
    stop_token = _current_control.set(control)
    conversation_token = _conversation_id.set(conversation_id or "default")
    sink_token = set_current_conversation(conversation) if conversation is not None else None
    try:
        yield
    finally:
        if conversation is not None:
            reset_current_conversation(sink_token)
        _current_control.reset(stop_token)
        _conversation_id.reset(conversation_token)
