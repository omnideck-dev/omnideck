"""Value objects shared by agent runners, managers, and adapters."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sdk.events import AgentEvent

if TYPE_CHECKING:
    from agents.types import Data


EventSink = Callable[[AgentEvent], None]


@dataclass(frozen=True, slots=True)
class AgentRunRequest:
    """Channel-neutral application input for work that currently becomes a turn.

    Channel adapters translate their native request into this type; the runner
    translates it into the SDK's conversation and turn primitives.
    """

    conversation_id: str
    message: str
    data: Sequence[Data] | None
    profile_id: str | None


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


__all__ = ["AgentRunInfo", "AgentRunRequest", "EventSink", "SequencedEvent"]
