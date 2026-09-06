"""Process-scoped run admission, task ownership, and channel-neutral handles."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Protocol
from uuid import uuid4

from conversations import get_or_create_conversation
from sdk.control import StopRequestedError
from sdk.events import AgentEvent, ErrorPayload
from sdk.turn import ExecutionResult

from ._models import AgentRunRequest, RunResult, RunSnapshot, SequencedEvent
from ._session import ConversationLoader, RunSession

logger = logging.getLogger(__name__)


class RunConflictError(RuntimeError):
    """A conversation already belongs to another active run."""


class AgentRuntimeClosedError(RuntimeError):
    """The runtime has stopped accepting runs."""


class _RunExecutor(Protocol):
    async def run(self, request: AgentRunRequest, session: RunSession) -> ExecutionResult: ...


class RunHandle:
    """Observe and control a run without owning its background task."""

    def __init__(self, session: RunSession) -> None:
        self._session = session

    @property
    def run_id(self) -> str:
        return self._session.run_id

    @property
    def conversation_id(self) -> str:
        return self._session.conversation_id

    def snapshot(self) -> RunSnapshot:
        return self._session.snapshot()

    def events(self, after_seq: int = 0) -> AsyncGenerator[SequencedEvent, None]:
        return self._session.events(after_seq)

    def sequence_for_event(self, event_id: str) -> int | None:
        return self._session.event_sequences.get(event_id)

    async def wait(self) -> RunResult:
        task = self._session.task
        if task is None:
            raise RuntimeError("Run task has not been started")
        # Cancelling a subscriber's wait must never cancel runtime-owned work.
        return await asyncio.shield(task)

    def stop(self) -> None:
        self._session.stop_event.set()

    def cancel(self) -> None:
        """Explicit owner cancellation, used when an owning routine is cancelled."""
        self.stop()
        if self._session.started and self._session.task is not None and not self._session.task.done():
            self._session.task.cancel()

    def nudge(self, message: str, *, execution_id: str | None = None) -> None:
        self._session.nudge(message, execution_id)


class AgentRuntime:
    """Own interactive and routine runs independently of their observers."""

    def __init__(
        self,
        runner: _RunExecutor | None = None,
        *,
        conversation_loader: ConversationLoader = get_or_create_conversation,
        shutdown_timeout: float = 5.0,
    ) -> None:
        from ._runner import AgentRunner

        self._runner = runner if runner is not None else AgentRunner()
        self._conversation_loader = conversation_loader
        self._shutdown_timeout = shutdown_timeout
        self._active_by_conversation: dict[str, RunSession] = {}
        self._runs_by_id: dict[str, RunSession] = {}
        self._closed = False

    async def start(self, request: AgentRunRequest) -> RunHandle:
        if self._closed:
            raise AgentRuntimeClosedError("Agent runtime is closed")
        if not request.conversation_id:
            raise ValueError("conversation_id is required")
        if request.conversation_id in self._active_by_conversation:
            raise RunConflictError(f"Conversation '{request.conversation_id}' already has an active run")
        # Reserve before the first await so concurrent starts cannot both enter.
        session = RunSession(request, f"run_{uuid4().hex}", self._conversation_loader)
        self._active_by_conversation[session.conversation_id] = session
        self._runs_by_id[session.run_id] = session
        session.task = asyncio.create_task(self._drive(session), name=f"agent-run-{session.run_id[4:12]}")
        return RunHandle(session)

    def get(self, run_id: str) -> RunHandle | None:
        session = self._runs_by_id.get(run_id)
        return RunHandle(session) if session is not None else None

    def active_for_conversation(self, conversation_id: str) -> RunHandle | None:
        session = self._active_by_conversation.get(conversation_id)
        return RunHandle(session) if session is not None else None

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        sessions = tuple(self._runs_by_id.values())
        for session in sessions:
            session.stop_event.set()
        tasks = tuple(session.task for session in sessions if session.task is not None and not session.task.done())
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=self._shutdown_timeout)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    async def _drive(self, session: RunSession) -> RunResult:
        session.started = True
        root = ExecutionResult("stopped")
        try:
            async with session:
                session.root_context.control.check_stop()
                try:
                    root = await self._runner.run(session.request, session)
                except (asyncio.CancelledError, StopRequestedError):
                    root = ExecutionResult("stopped")
                except Exception as exc:
                    root = self._failure(session, exc)
        except (asyncio.CancelledError, StopRequestedError):
            root = ExecutionResult("stopped")
        except Exception as exc:
            root = self._failure(session, exc)
        finally:
            self._active_by_conversation.pop(session.conversation_id, None)
            self._runs_by_id.pop(session.run_id, None)
        return session.finish(root)

    @staticmethod
    def _failure(session: RunSession, exc: Exception) -> ExecutionResult:
        logger.exception("Agent run failed: %s", session.run_id)
        if not any(
            isinstance(record.event.payload, ErrorPayload) and record.event.depth in (None, 0)
            for record in session.records
        ):
            session.add_event(
                AgentEvent(
                    payload=ErrorPayload(
                        type="error",
                        message="An error occurred while processing your message.",
                    )
                )
            )
        return ExecutionResult("error", error=str(exc))


__all__ = ["AgentRuntime", "AgentRuntimeClosedError", "RunConflictError", "RunHandle"]
