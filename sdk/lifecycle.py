"""Runtime resource lifecycle hooks.

Subsystems that allocate per-agent or per-conversation resources register a
cleanup callback here. Runtime boundaries invoke them when an agent span ends
or a conversation leaves the live cache without depending on those subsystems.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

AgentSpanExitHook = Callable[[str], Awaitable[None]]

_hooks: list[AgentSpanExitHook] = []


def register_agent_span_exit_hook(fn: AgentSpanExitHook) -> None:
    """Register a callback to run when any agent span completes."""
    if fn not in _hooks:
        _hooks.append(fn)


async def run_agent_span_exit_hooks(context_id: str) -> None:
    """Run all registered exit hooks for the given agent context."""
    for fn in _hooks:
        try:
            await fn(context_id)
        except Exception:  # noqa: BLE001
            logger.debug("Agent span exit hook %s failed for '%s'", fn.__name__, context_id)


ConversationExitHook = Callable[[str], Awaitable[None]]

_conversation_hooks: list[ConversationExitHook] = []


def register_conversation_exit_hook(fn: ConversationExitHook) -> None:
    """Register a callback to run when a conversation leaves the live cache."""
    if fn not in _conversation_hooks:
        _conversation_hooks.append(fn)


async def run_conversation_exit_hooks(conversation_id: str) -> None:
    """Run all registered exit hooks for the given conversation."""
    for fn in _conversation_hooks:
        try:
            await fn(conversation_id)
        except Exception:  # noqa: BLE001
            logger.debug(
                "Conversation exit hook %s failed for '%s'",
                fn.__name__,
                conversation_id,
            )
