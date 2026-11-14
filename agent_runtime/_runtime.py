"""Process-scoped run admission, task ownership, and channel-neutral handles."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable, Iterator
from contextlib import contextmanager
from typing import Protocol
from uuid import uuid4
from integrations.connection_cache import IntegrationConnectionCache

from goals._store import GoalStore
from goals._models import Goal, GoalHistoryEntry
from ._goal_events import goal_transition_event
from conversations import ConversationStore, EventsLogWriter
from browser.runtime import BrowserRuntime
from agent_core.control import StopRequestedError
from agent_core.events import AgentEvent, ErrorPayload
from agent_core.turn import ExecutionResult

from ._models import AgentRunRequest, QueuedMessage, RunResult, RunSnapshot, SequencedEvent
from ._session import RunSession

logger = logging.getLogger(__name__)


class RunConflictError(RuntimeError):
    """A conversation already belongs to another active run."""


class AgentRuntimeClosedError(RuntimeError):
    """The runtime has stopped accepting runs."""


class AttachmentsWhileRunningError(ValueError):
    """Files cannot be queued for an agent that is already working."""


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

    def nudge(self, message: str, *, execution_id: str | None = None) -> str:
        return self._session.nudge(message, execution_id)

    def remove_nudge(self, nudge_id: str) -> bool:
        """Remove a queued root message. Returns False when the agent already read it."""
        return self._session.remove_root_message(nudge_id)


class AgentRuntime:
    """Own interactive and routine runs independently of their observers."""

    def __init__(
        self,
        runner: _RunExecutor | None = None,
        *,
        conversations: ConversationStore | None = None,
        browser_runtime: BrowserRuntime | None = None,
        integration_cache: IntegrationConnectionCache | None = None,
        shutdown_timeout: float = 5.0,
        goal_store: GoalStore | None = None,
        goals_enabled: Callable[[], bool] | None = None,
    ) -> None:
        from ._runner import AgentRunner

        if isinstance(runner, AgentRunner):
            if browser_runtime is not None and browser_runtime is not runner.browser_runtime:
                raise ValueError("AgentRunner and AgentRuntime must share one browser runtime")
            browser_runtime = runner.browser_runtime
            if goal_store is not None and runner.goal_store is not goal_store:
                raise ValueError("AgentRunner and AgentRuntime must share one goal store")
            goal_store = runner.goal_store
            if goals_enabled is None:
                goals_enabled = runner.goals_enabled
            else:
                runner.goals_enabled = goals_enabled
        self.conversations = conversations if conversations is not None else ConversationStore()
        self._browser = browser_runtime if browser_runtime is not None else BrowserRuntime()
        self._goals_enabled = goals_enabled if goals_enabled is not None else lambda: True
        self._runner = runner if runner is not None else AgentRunner(
            browser_runtime=self._browser, goal_store=goal_store, goals_enabled=self._goals_enabled,
        )
        self._goal_store = goal_store
        self._shutdown_timeout = shutdown_timeout
        self._integration_cache = integration_cache
        self._active_by_conversation: dict[str, RunSession] = {}
        self._runs_by_id: dict[str, RunSession] = {}
        self._closed = False
        self._run_observers: set[Callable[[RunHandle], None]] = set()
        self._event_observers: set[Callable[[str, AgentEvent], None]] = set()
        self._unsubscribe_goals = (
            self._goal_store.subscribe(self._record_goal_change) if self._goal_store is not None else None
        )

    def _record_goal_change(self, goal: Goal, entries: list[GoalHistoryEntry]) -> None:
        session = self._active_by_conversation.get(goal.conversation_id)
        writer = EventsLogWriter(goal.conversation_id)
        for entry in entries:
            event = goal_transition_event(goal.id, entry)
            if event is not None:
                writer.handle_event(event)
                if session is not None:
                    session.stream_persisted_event(event)

    async def start(self, request: AgentRunRequest) -> RunHandle:
        if self._closed:
            raise AgentRuntimeClosedError("Agent runtime is closed")
        if not request.conversation_id:
            raise ValueError("conversation_id is required")
        if request.conversation_id in self._active_by_conversation:
            raise RunConflictError(f"Conversation '{request.conversation_id}' already has an active run")
        # Reserve before the first await so concurrent starts cannot both enter.
        session = RunSession(
            request, f"run_{uuid4().hex}", self.conversations,
            integration_connections=self._integration_cache.snapshot() if self._integration_cache else (),
            event_observers=self._event_observers,
        )
        self._active_by_conversation[session.conversation_id] = session
        self._runs_by_id[session.run_id] = session
        session.task = asyncio.create_task(self._drive(session), name=f"agent-run-{session.run_id[4:12]}")
        handle = RunHandle(session)
        for observer in tuple(self._run_observers):
            try:
                observer(handle)
            except Exception:
                logger.exception("Run observer failed")
        return handle

    @contextmanager
    def observe_runs(self, on_start: Callable[[RunHandle], None]) -> Iterator[tuple[RunHandle, ...]]:
        """Observe new runs and capture the currently active handles atomically."""
        self._run_observers.add(on_start)
        try:
            yield tuple(RunHandle(session) for session in self._active_by_conversation.values())
        finally:
            self._run_observers.discard(on_start)

    async def send(self, request: AgentRunRequest) -> RunHandle | QueuedMessage:
        """Send a user message: queue it for a working agent, or start a run."""
        while True:
            session = self._active_by_conversation.get(request.conversation_id)
            if session is None:
                return await self.start(request)
            # Check and queue with no await between them, so the agent cannot
            # finish in between and drop the message.
            if session.accepts_root_messages():
                if request.attachments:
                    raise AttachmentsWhileRunningError("Files can be sent after the agent finishes.")
                nudge_id = session.queue_root_message(request.message, request.context)
                return QueuedMessage(nudge_id, session.run_id)
            # The run is ending. Start a new one once it has finished.
            assert session.task is not None  # start() creates the task before returning.
            await asyncio.wait({session.task})

    def observe_events(self, handler: Callable[[str, AgentEvent], None]) -> Callable[[], None]:
        """Call handler with the conversation ID and each event any run publishes.

        Returns a function that stops observing.
        """
        self._event_observers.add(handler)
        return lambda: self._event_observers.discard(handler)

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

        try:
            await self.conversations.close()
        finally:
            await self._browser.close()
            if self._unsubscribe_goals is not None:
                self._unsubscribe_goals()

    async def _drive(self, session: RunSession) -> RunResult:
        session.started = True
        root = ExecutionResult("stopped")
        goal_id = None
        trigger = session.request.goal_trigger
        claim_id = trigger.claim_id if trigger is not None else session.run_id
        try:
            if trigger is not None and not self._goals_enabled():
                raise StopRequestedError()
            if self._goal_store is not None and self._goals_enabled():
                if trigger is not None:
                    goal = self._goal_store.get(trigger.goal_id)
                    if (
                        goal is None or goal.conversation_id != session.conversation_id
                        or goal.claim is None or goal.claim.id != claim_id
                    ):
                        raise StopRequestedError()
                else:
                    # A chat turn owns the goal without taking its wake, paused or not.
                    goal = self._goal_store.current(session.conversation_id)
                    if goal is not None:
                        goal = self._goal_store.claim_for_turn(goal.id, claim_id)
                if goal is not None:
                    goal_id = goal.id
                    self._goal_store.bind_run(goal_id, claim_id, session.run_id)
            elif trigger is not None:
                raise RuntimeError("Goal wakeup requires a configured goal store")
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
            session.return_unread()
            try:
                # Preserve interrupted ownership on shutdown so restart recovery
                # can ask the agent to reconcile its last actions exactly once.
                if (
                    self._goal_store is not None and goal_id is not None
                    and not (self._closed and root.status == "stopped")
                ):
                    self._goal_store.finish_run(
                        goal_id, claim_id, session.run_id, root.status, error=root.error,
                    )
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


__all__ = ["AgentRuntime", "AgentRuntimeClosedError", "AttachmentsWhileRunningError", "RunConflictError", "RunHandle"]
