"""Value objects shared by agent runners, managers, and adapters."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sdk.events import AgentEvent

EventSink = Callable[[AgentEvent], None]


@dataclass(frozen=True, slots=True)
class RunAttachment:
    """One file attached to an agent run."""

    base64_encoded: str
    content_type: str
    filename: str | None = None


@dataclass(frozen=True, slots=True)
class AgentRunRequest:
    """Channel-neutral application input for work that currently becomes a turn.

    Channel adapters translate their native request into this type; the runner
    translates it into the SDK's conversation and turn primitives.
    """

    conversation_id: str
    message: str
    attachments: Sequence[RunAttachment] | None
    profile_id: str | None
    # Assigned by the runtime at admission; direct runners may allocate it.
    run_id: str | None = None


@dataclass(frozen=True, slots=True)
class SequencedEvent:
    """One agent event plus its ordered replay cursor within a run."""

    run_id: str
    seq: int
    event: AgentEvent


@dataclass(frozen=True, slots=True)
class AgentRunInfo:
    """Read-only view of an active agent run."""

    run_id: str
    conversation_id: str
    last_seq: int


__all__ = [
    "AgentRunInfo",
    "AgentRunRequest",
    "EventSink",
    "RunAttachment",
    "SequencedEvent",
]
