"""Application-level orchestration for durable agent runs.

``Agent run`` is the channel-neutral application vocabulary layered over the
SDK's existing ``turn`` vocabulary. A turn still describes the scoped SDK
execution of one user-message/agent-response cycle. A run describes the work
that an application starts, owns, observes, stops, and reconnects to.

Today one run drives one root turn. Keeping the concepts separate lets HTTP,
Telegram, Slack, and future non-chat interfaces share the same runtime without
making "chat request" the primary abstraction of the public API.
"""

from ._active_runs import (
    ActiveRunConflictError,
    ActiveRunError,
    ActiveRunManager,
    ActiveRunManagerClosedError,
    InvalidRunCursorError,
    UnknownActiveRunError,
)
from ._models import AgentRunInfo, AgentRunRequest, EventSink, SequencedEvent
from ._runner import AgentRunner, ConversationLoader

__all__ = [
    "ActiveRunConflictError",
    "ActiveRunError",
    "ActiveRunManager",
    "ActiveRunManagerClosedError",
    "AgentRunInfo",
    "AgentRunRequest",
    "AgentRunner",
    "ConversationLoader",
    "EventSink",
    "InvalidRunCursorError",
    "SequencedEvent",
    "UnknownActiveRunError",
]
