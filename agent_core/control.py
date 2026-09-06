"""Control signals supplied by the owner of an agent execution."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field


class StopRequestedError(Exception):
    """Raised at safe checkpoints when execution is asked to stop."""


@dataclass
class ExecutionControl:
    """A shared stop signal and an execution-local nudge inbox."""

    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    nudges: list[str] = field(default_factory=list)

    def stop(self) -> None:
        self.stop_event.set()

    def check_stop(self) -> None:
        if self.stop_event.is_set():
            raise StopRequestedError()

    def nudge(self, message: str) -> None:
        self.nudges.append(message)

    def drain_nudges(self) -> list[str]:
        messages = self.nudges[:]
        self.nudges.clear()
        return messages


_current_control: ContextVar[ExecutionControl | None] = ContextVar("execution_control", default=None)


def get_execution_control() -> ExecutionControl | None:
    """Return the control supplied to the current execution scope."""
    return _current_control.get()
