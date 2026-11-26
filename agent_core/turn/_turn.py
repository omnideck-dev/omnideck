"""Conversation identity and cooperative stop checks for agent core callers.

Run admission, liveness, remote controls, and terminal events belong to the
application runtime.
"""

from __future__ import annotations

from contextvars import ContextVar

from agent_core.control import _current_control

_conversation_id: ContextVar[str | None] = ContextVar("turn_conversation_id", default=None)


def get_conversation_id() -> str | None:
    return _conversation_id.get()


def check_stop() -> None:
    control = _current_control.get()
    if control is not None:
        control.check_stop()
