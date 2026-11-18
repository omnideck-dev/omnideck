"""A feature's part in every root run, without the runtime knowing the feature."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from agent_core.events import AgentEvent
from agent_core.skills import Skill
from agent_core.turn import ExecutionResult

from ._models import AgentRunRequest

if TYPE_CHECKING:
    from ._session import RunSession


@dataclass(frozen=True, slots=True)
class RunAdditions:
    """What an extension adds to one root run.

    Attributes:
        skills: Granted to the root agent for this run only.
        opening_events: Published in order inside the run, before its first
            message.
    """

    skills: tuple[Skill, ...] = ()
    opening_events: tuple[AgentEvent, ...] = ()


class RunExtension(Protocol):
    """A feature's part in every root run. Sub-agents never see extensions.

    ``before_run`` runs inside the run, before the root agent starts. It may
    stop the run by raising ``StopRequestedError``. ``after_run`` runs once
    for every extension whose ``before_run`` returned, after the root agent
    finished. The events it returns are published inside the run, before its
    end marker. ``shutting_down`` is true when the runtime closed and stopped
    the run.
    """

    async def before_run(self, request: AgentRunRequest, run: RunSession) -> RunAdditions | None: ...

    def after_run(
        self, request: AgentRunRequest, run: RunSession, result: ExecutionResult, *, shutting_down: bool,
    ) -> Sequence[AgentEvent]: ...


__all__ = ["RunAdditions", "RunExtension"]
