"""Cleanup hooks for resources scoped to a live conversation."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

ConversationExitHook = Callable[[str], Awaitable[None]]

_hooks: list[ConversationExitHook] = []


def register_conversation_exit_hook(fn: ConversationExitHook) -> None:
    """Register a callback to run when a conversation leaves live state."""
    if fn not in _hooks:
        _hooks.append(fn)


async def run_conversation_exit_hooks(conversation_id: str) -> None:
    """Run all registered exit hooks for the given conversation."""
    for fn in _hooks:
        try:
            await fn(conversation_id)
        except Exception:  # noqa: BLE001
            logger.debug(
                "Conversation exit hook %s failed for '%s'",
                fn.__name__,
                conversation_id,
            )
