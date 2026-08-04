"""Process-scoped ownership and event replay for active agent runs."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Protocol

from agent_runtime._models import AgentRunInfo, AgentRunRequest, EventSink, SequencedEvent
from sdk.events import AgentEvent

logger = logging.getLogger(__name__)


class _RunExecutor(Protocol):
    """Execution contract consumed by the active-run manager."""

    async def run(
        self,
        request: AgentRunRequest,
        *,
        emit: EventSink,
        stop_event: asyncio.Event,
    ) -> None: ...


class ActiveRunError(RuntimeError):
    """Base class for active-run manager failures."""


class ActiveRunConflictError(ActiveRunError):
    """Raised when a conversation already has an active run."""


class ActiveRunManagerClosedError(ActiveRunError):
    """Raised when work is submitted during application shutdown."""


class UnknownActiveRunError(ActiveRunError):
    """Raised when a run is absent or has already completed."""


class InvalidRunCursorError(ActiveRunError):
    """Raised when a subscriber requests an impossible event sequence."""


@dataclass(slots=True)
class _ActiveRun:
    run_id: str
    conversation_id: str
    stop_event: asyncio.Event
    records: list[SequencedEvent] = field(default_factory=list)
    event_sequences: dict[str, int] = field(default_factory=dict)
    waiters: set[asyncio.Event] = field(default_factory=set)
    task: asyncio.Task[None] | None = None
    completed: bool = False

    def append(self, event: AgentEvent) -> None:
        """Append an event and synchronously wake every subscriber."""
        if self.completed:
            logger.warning(
                "Ignoring event after active run completed: run=%s event=%s",
                self.run_id,
                event.id,
            )
            return

        seq = len(self.records) + 1
        self.records.append(
            SequencedEvent(
                run_id=self.run_id,
                seq=seq,
                event=event,
            )
        )
        self.event_sequences[event.id] = seq

        for waiter in tuple(self.waiters):
            waiter.set()

    def finish(self) -> None:
        """Mark the run complete and wake subscribers beyond its final event."""
        self.completed = True
        for waiter in tuple(self.waiters):
            waiter.set()

    def info(self) -> AgentRunInfo:
        """Return a read-only snapshot of this run's current state."""
        return AgentRunInfo(
            run_id=self.run_id,
            conversation_id=self.conversation_id,
            last_seq=len(self.records),
        )


class ActiveRunManager:
    """Own agent runs independently from any channel subscriber."""

    def __init__(
        self,
        runner: _RunExecutor,
        *,
        shutdown_timeout: float = 5.0,
    ) -> None:
        self._runner = runner
        self._shutdown_timeout = shutdown_timeout
        self._active_by_conversation: dict[str, _ActiveRun] = {}
        self._runs_by_id: dict[str, _ActiveRun] = {}
        self._closed = False

    async def start(self, request: AgentRunRequest) -> AgentRunInfo:
        """Reserve a conversation and start its run in a background task."""
        if self._closed:
            raise ActiveRunManagerClosedError("Active run manager is closed")
        if request.conversation_id in self._active_by_conversation:
            raise ActiveRunConflictError(
                f"Conversation '{request.conversation_id}' already has an active run",
            )

        # This method intentionally performs no awaits before reservation and
        # task creation. On one event loop, concurrent starts therefore cannot
        # both pass the active-conversation check.
        run = _ActiveRun(
            run_id=f"run_{uuid.uuid4().hex}",
            conversation_id=request.conversation_id,
            stop_event=asyncio.Event(),
        )
        self._active_by_conversation[request.conversation_id] = run
        self._runs_by_id[run.run_id] = run
        run.task = asyncio.create_task(
            self._drive(run, request),
            name=f"agent-run-{run.run_id[4:12]}",
        )
        return run.info()

    def active_for_conversation(
        self,
        conversation_id: str,
    ) -> AgentRunInfo | None:
        """Return the conversation's active run, if any."""
        run = self._active_by_conversation.get(conversation_id)
        return run.info() if run is not None else None

    def get(self, run_id: str) -> AgentRunInfo | None:
        """Return an active run by ID, if present."""
        run = self._runs_by_id.get(run_id)
        return run.info() if run is not None else None

    def sequence_for_event(self, run_id: str, event_id: str) -> int | None:
        """Resolve a stable domain event ID to its active-run cursor."""
        run = self._runs_by_id.get(run_id)
        if run is None:
            return None
        return run.event_sequences.get(event_id)

    def subscribe(
        self,
        run_id: str,
        *,
        after_seq: int,
    ) -> AsyncGenerator[SequencedEvent, None]:
        """Return retained events followed by live events for an active run.

        This is a regular method rather than an async-generator method so the
        run reference is captured immediately. An initial adapter can therefore
        subscribe before a very fast runner completes and is pruned.
        """
        run = self._runs_by_id.get(run_id)
        if run is None:
            raise UnknownActiveRunError(f"Unknown or completed run '{run_id}'")
        if after_seq < 0 or after_seq > len(run.records):
            raise InvalidRunCursorError(
                f"Cursor {after_seq} is invalid for run '{run_id}'",
            )
        return self._iterate(run, after_seq=after_seq)

    def request_stop(self, conversation_id: str) -> bool:
        """Set a run's stop signal, including before its runner starts."""
        run = self._active_by_conversation.get(conversation_id)
        if run is None:
            return False
        run.stop_event.set()
        return True

    async def close(self) -> None:
        """Stop accepting work, request graceful stops, then cancel stragglers."""
        if self._closed:
            return
        self._closed = True

        runs = tuple(self._active_by_conversation.values())
        for run in runs:
            run.stop_event.set()

        tasks = tuple(run.task for run in runs if run.task is not None and not run.task.done())
        if not tasks:
            return

        _done, pending = await asyncio.wait(
            tasks,
            timeout=self._shutdown_timeout,
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _drive(self, run: _ActiveRun, request: AgentRunRequest) -> None:
        """Drive one run without taking ownership of its domain events."""
        try:
            await self._runner.run(
                request,
                emit=run.append,
                stop_event=run.stop_event,
            )
        except asyncio.CancelledError:
            logger.info("Active agent run cancelled: %s", run.run_id)
            raise
        except Exception:
            # AgentRunner owns user-facing errors and terminal domain events.
            # The manager only contains an unexpected runner failure so its
            # background task does not leak an unhandled exception.
            logger.exception("Agent runner exited with an unhandled error: %s", run.run_id)
        finally:
            run.finish()
            self._remove(run)

    async def _iterate(
        self,
        run: _ActiveRun,
        *,
        after_seq: int,
    ) -> AsyncGenerator[SequencedEvent, None]:
        """Yield a captured run without coupling its task to this iterator."""
        wake = asyncio.Event()
        run.waiters.add(wake)
        next_seq = after_seq + 1
        try:
            while True:
                # Clear before inspecting shared state. append()/finish() cannot
                # interleave until the next await, so a wakeup cannot be lost.
                wake.clear()
                while next_seq <= len(run.records):
                    record = run.records[next_seq - 1]
                    next_seq += 1
                    yield record
                if run.completed:
                    return
                await wake.wait()
        finally:
            run.waiters.discard(wake)

    def _remove(self, run: _ActiveRun) -> None:
        """Prune completed lookup entries without disturbing captured subscribers."""
        if self._active_by_conversation.get(run.conversation_id) is run:
            del self._active_by_conversation[run.conversation_id]
        if self._runs_by_id.get(run.run_id) is run:
            del self._runs_by_id[run.run_id]


__all__ = [
    "ActiveRunConflictError",
    "ActiveRunError",
    "ActiveRunManager",
    "ActiveRunManagerClosedError",
    "InvalidRunCursorError",
    "UnknownActiveRunError",
]
