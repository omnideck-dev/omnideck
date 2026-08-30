"""Application-level provenance for conversation Browser sessions.

The browser pool deliberately owns only Chromium contexts.  This module keeps
the product concepts needed to decide when a conversation context must be
replaced and which saved profile that live context may update during takeover.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from tools.browser.core.pool import release_conversation_browser


@dataclass(frozen=True, slots=True)
class ConversationBrowserSession:
    """The configured assignment and actual source of one live session."""

    agent_profile_id: str
    browser_access: bool
    configured_profile_id: str | None
    source_profile_id: str | None

    @property
    def configuration(self) -> tuple[str, bool, str | None]:
        """Return the values that require a fresh context when changed."""
        return (
            self.agent_profile_id,
            self.browser_access,
            self.configured_profile_id,
        )


class ConversationBrowserRegistry:
    """Own provenance for all live conversation Browser sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, ConversationBrowserSession] = {}

    def get(self, conversation_id: str) -> ConversationBrowserSession | None:
        return self._sessions.get(conversation_id)

    def set(self, conversation_id: str, session: ConversationBrowserSession) -> None:
        self._sessions[conversation_id] = session

    def remove(self, conversation_id: str) -> None:
        self._sessions.pop(conversation_id, None)

    def items(self) -> list[tuple[str, ConversationBrowserSession]]:
        return list(self._sessions.items())

    def clear(self) -> None:
        self._sessions.clear()


_registry = ConversationBrowserRegistry()
_cleanup_registered = False


async def prepare_conversation_browser(
    conversation_id: str,
    *,
    agent_profile_id: str,
    browser_access: bool,
    configured_profile_id: str | None,
    source_profile_id: str | None,
) -> ConversationBrowserSession:
    """Prepare provenance for a turn, replacing an incompatible live context.

    A context continues across turns only while the same agent profile and
    Browser assignment remain selected.  This prevents an agent switch from
    inheriting another agent's cookies, including when both agents use Empty.
    """
    next_session = ConversationBrowserSession(
        agent_profile_id=agent_profile_id,
        browser_access=browser_access,
        configured_profile_id=configured_profile_id,
        source_profile_id=source_profile_id if browser_access else None,
    )
    current = _registry.get(conversation_id)
    if current is not None and current.configuration != next_session.configuration:
        await release_conversation_browser(conversation_id)
        current = None
    if current is None:
        _registry.set(conversation_id, next_session)
        return next_session
    return current


def get_conversation_browser_session(
    conversation_id: str,
) -> ConversationBrowserSession | None:
    """Return provenance for the conversation's current Browser context."""
    return _registry.get(conversation_id)


def set_conversation_browser_source_profile_id(
    conversation_id: str,
    profile_id: str,
    *,
    assigned_to_agent: bool = False,
) -> None:
    """Associate a newly saved profile with the unchanged live context."""
    current = _registry.get(conversation_id)
    if current is None:
        return
    _registry.set(
        conversation_id,
        replace(
            current,
            source_profile_id=profile_id,
            configured_profile_id=(profile_id if assigned_to_agent else current.configured_profile_id),
        ),
    )


def detach_deleted_browser_profile(profile_id: str) -> None:
    """Detach a removed profile from live or disabled session metadata."""
    for conversation_id, current in _registry.items():
        source_profile_id = None if current.source_profile_id == profile_id else current.source_profile_id
        configured_profile_id = current.configured_profile_id
        if not current.browser_access and configured_profile_id == profile_id:
            configured_profile_id = None
        if source_profile_id != current.source_profile_id or configured_profile_id != current.configured_profile_id:
            _registry.set(
                conversation_id,
                replace(
                    current,
                    source_profile_id=source_profile_id,
                    configured_profile_id=configured_profile_id,
                ),
            )


async def _forget_conversation_browser_session(conversation_id: str) -> None:
    _registry.remove(conversation_id)


def register_conversation_browser_cleanup() -> None:
    """Attach registry cleanup at application initialization, once."""
    global _cleanup_registered
    if _cleanup_registered:
        return
    from sdk.events import register_conversation_exit_hook

    register_conversation_exit_hook(_forget_conversation_browser_session)
    _cleanup_registered = True


def reset_conversation_browser_sessions() -> None:
    """Clear live provenance, primarily for isolated application tests."""
    _registry.clear()


__all__ = [
    "ConversationBrowserSession",
    "ConversationBrowserRegistry",
    "detach_deleted_browser_profile",
    "get_conversation_browser_session",
    "prepare_conversation_browser",
    "register_conversation_browser_cleanup",
    "reset_conversation_browser_sessions",
    "set_conversation_browser_source_profile_id",
]
