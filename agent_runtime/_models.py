"""Value objects shared by agent runners, sessions, and adapters."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from agent_core.turn import ExecutionResult
from agent_core.providers import TokenUsage
from agent_core.events import FileOutputPayload

from agent_core.events import AgentEvent


@dataclass(frozen=True, slots=True)
class RunAttachment:
    """One file attached to an agent run."""

    base64_encoded: str
    content_type: str
    filename: str | None = None


@dataclass(frozen=True, slots=True)
class RunPolicy:
    """Explicit history, prompt, and resource lifetime choices for a root run."""

    restore_skills: bool = True
    persist_skills: bool = True
    include_memory: bool = True
    conversation_lifetime: Literal["cached", "run"] = "cached"
    agent_name: str | None = None


@dataclass(frozen=True, slots=True)
class AgentRunRequest:
    """Channel-neutral application input for work that currently becomes a turn.

    Channel adapters translate their native request into this type; the runner
    translates it into the agent core's conversation and turn primitives.
    """

    conversation_id: str
    message: str
    attachments: Sequence[RunAttachment] | None
    profile_id: str | None
    policy: RunPolicy = RunPolicy()


@dataclass(frozen=True, slots=True)
class SequencedEvent:
    """One agent event plus its ordered replay cursor within a run."""

    run_id: str
    seq: int
    event: AgentEvent


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    """Read-only view of an active agent run."""

    run_id: str
    conversation_id: str
    last_seq: int
    status: str


@dataclass(frozen=True, slots=True)
class RunResult:
    """Root completion plus artifacts and usage aggregated across its execution tree."""

    run_id: str
    conversation_id: str
    root: ExecutionResult
    usage: TokenUsage
    artifacts: tuple[FileOutputPayload, ...]
    executions: tuple[tuple[str, ExecutionResult], ...]

    @property
    def status(self) -> str:
        return self.root.status

    @property
    def output(self) -> str | None:
        return self.root.output

    def raise_for_status(self) -> None:
        self.root.raise_for_status()


__all__ = ["AgentRunRequest", "RunAttachment", "RunPolicy", "RunResult", "RunSnapshot", "SequencedEvent"]
