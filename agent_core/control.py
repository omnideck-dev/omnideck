"""Control signals supplied by the owner of an agent execution."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import uuid4
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_core.events._models import GoalQuestionContext, UserMessagePayload


class StopRequestedError(Exception):
    """Raised at safe checkpoints when execution is asked to stop."""


@dataclass
class ExecutionControl:
    """A shared stop signal and an execution-local nudge inbox."""

    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    nudges: list[UserMessagePayload] = field(default_factory=list)
    accepting_nudges: bool = True

    def stop(self) -> None:
        self.stop_event.set()

    def check_stop(self) -> None:
        if self.stop_event.is_set():
            raise StopRequestedError()

    def nudge(self, message: str, *, context: tuple[GoalQuestionContext, ...] = ()) -> str:
        """Queue a message for the agent's next step and return its nudge ID."""
        if not self.accepting_nudges:
            raise ValueError("This execution has finished. Send a new message instead.")
        from agent_core.events._models import UserMessagePayload

        nudge_id = uuid4().hex
        self.nudges.append(UserMessagePayload(
            type="user_message", content=message, context=list(context), is_nudge=True, nudge_id=nudge_id,
        ))
        return nudge_id

    def remove_nudge(self, nudge_id: str) -> bool:
        """Remove a queued message. Returns False when the agent already read it."""
        for index, message in enumerate(self.nudges):
            if message.nudge_id == nudge_id:
                del self.nudges[index]
                return True
        return False

    def drain_nudges(self) -> list[UserMessagePayload]:
        messages = self.nudges[:]
        self.nudges.clear()
        return messages

    def return_unread(self) -> list[UserMessagePayload]:
        """Stop accepting messages and take every message the agent never read."""
        self.accepting_nudges = False
        return self.drain_nudges()


_current_control: ContextVar[ExecutionControl | None] = ContextVar("execution_control", default=None)


def get_execution_control() -> ExecutionControl | None:
    """Return the control supplied to the current execution scope."""
    return _current_control.get()
