"""Run-owned execution controls, history resources, event replay, and completion."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AsyncExitStack
from uuid import uuid4

from artifacts import ArtifactsIndexWriter
from conversations import BrowserTabsWriter, EventsLogWriter, TerminalWriter, run_conversation_exit_hooks
from conversations._cache import conversation_lease
from sdk.context import ConversationHistory
from sdk.control import ExecutionControl
from sdk.events import AgentEvent, FileOutputPayload, TurnEndPayload
from sdk.providers import TokenUsage
from sdk.turn import ExecutionContext, ExecutionResult, get_execution_context

from ._models import AgentRunRequest, RunResult, RunSnapshot, SequencedEvent

logger = logging.getLogger(__name__)
ConversationLoader = Callable[[str], Awaitable[ConversationHistory]]


class InvalidRunCursorError(ValueError):
    """A replay cursor is outside the available run event sequence."""


class RunSession:
    """Own one accepted run and every execution underneath its root."""

    def __init__(self, request: AgentRunRequest, run_id: str, loader: ConversationLoader) -> None:
        self.request = request
        self.run_id = run_id
        self.conversation_id = request.conversation_id
        self._loader = loader
        self.stop_event = asyncio.Event()
        self.history: ConversationHistory | None = None
        self.records: list[SequencedEvent] = []
        self.event_sequences: dict[str, int] = {}
        self.waiters: set[asyncio.Event] = set()
        self.task: asyncio.Task[RunResult] | None = None
        self.result: RunResult | None = None
        self.completed = False
        self.started = False
        self._terminal_sent = False
        self._attached = False
        self._resources = AsyncExitStack()
        self._artifacts: list[FileOutputPayload] = []
        self._results: dict[str, ExecutionResult] = {}
        # Preserve the dotted identity contract used by persisted conversation readers.
        self.root_context = ExecutionContext(
            execution_id=f"root.agent.{uuid4().hex}",
            conversation_id=self.conversation_id,
            run_id=run_id,
            event_sink=self,
            control=ExecutionControl(self.stop_event),
        )
        self.executions: dict[str, ExecutionContext] = {self.root_context.execution_id: self.root_context}

    async def __aenter__(self) -> RunSession:
        try:
            self._resources.enter_context(conversation_lease(self.conversation_id))
            if self.request.policy.conversation_lifetime == "run":
                self._resources.push_async_callback(run_conversation_exit_hooks, self.conversation_id)
                self.history = ConversationHistory(conversation_id=self.conversation_id)
            else:
                self.history = await self._loader(self.conversation_id)
            observers = [
                EventsLogWriter(self.conversation_id).handle_event,
                BrowserTabsWriter(self.conversation_id).handle_event,
                TerminalWriter(self.conversation_id).handle_event,
                ArtifactsIndexWriter(self.conversation_id).handle_event,
            ]
            # Exit-stack ordering: detach all observers before the first await;
            # drain their pending tasks before conversation resource cleanup.
            self._resources.push_async_callback(self.history.drain_observers)
            for observer in [*observers, self._record]:
                self.history.subscribe(observer)
            self._attached = True
            self._resources.callback(self._detach, [*observers, self._record])
            return self
        except BaseException:
            await self._resources.aclose()
            raise

    async def __aexit__(self, *exc: object) -> None:
        await self._resources.aclose()

    def _detach(self, observers: list[Callable[[AgentEvent], object]]) -> None:
        self._attached = False
        if self.history is not None:
            for observer in observers:
                self.history.unsubscribe(observer)

    def add_event(self, event: AgentEvent) -> None:
        """Canonical SDK event destination; history fans out to writers and replay."""
        if self.history is not None and self._attached:
            self.history.add_event(event)
        else:
            self._record(event)

    def subscribe(self, handler: Callable[[AgentEvent], object]) -> None:
        if self.history is None:
            raise RuntimeError("Run history is not prepared")
        self.history.subscribe(handler)

    def unsubscribe(self, handler: Callable[[AgentEvent], object]) -> None:
        if self.history is not None:
            self.history.unsubscribe(handler)

    def _record(self, event: AgentEvent) -> None:
        if self.completed:
            return
        if event.payload.type == "turn_end":
            # Only this session owns the root terminal event, including when a
            # misbehaving supplied runner tries to publish one prematurely.
            if not self._terminal_sent:
                return
            if self.records and self.records[-1].event.payload.type == "turn_end":
                return
        seq = len(self.records) + 1
        self.records.append(SequencedEvent(self.run_id, seq, event))
        self.event_sequences[event.id] = seq
        if isinstance(event.payload, FileOutputPayload):
            self._artifacts.append(event.payload)
        for waiter in tuple(self.waiters):
            waiter.set()

    def end_events(self) -> None:
        if not self._terminal_sent:
            self._terminal_sent = True
            self.add_event(AgentEvent(payload=TurnEndPayload(type="turn_end")))

    def require_parent(self, parent: ExecutionContext) -> None:
        if self.executions.get(parent.execution_id) is not parent or get_execution_context() is not parent:
            raise RuntimeError("Spawn tool is only valid inside its owning parent execution")

    def create_child(self, parent: ExecutionContext) -> ExecutionContext:
        self.require_parent(parent)
        parent.control.check_stop()
        from sdk.events import get_current_agent_name

        child = ExecutionContext(
            execution_id=f"{parent.execution_id}.agent.{uuid4().hex}",
            conversation_id=self.conversation_id,
            run_id=self.run_id,
            event_sink=self,
            control=ExecutionControl(self.stop_event),
            parent_execution_id=parent.execution_id,
            ancestors=(*parent.ancestors, (parent.execution_id, get_current_agent_name())),
        )
        self.executions[child.execution_id] = child
        return child

    def finish_execution(self, execution: ExecutionContext, result: ExecutionResult) -> None:
        self.executions.pop(execution.execution_id, None)
        self._results[execution.execution_id] = result

    def nudge(self, message: str, execution_id: str | None = None) -> None:
        target = self.executions.get(execution_id or self.root_context.execution_id)
        if target is None or self.completed:
            raise ValueError("No active execution with that identity in this run")
        target.control.nudge(message)

    def finish(self, root: ExecutionResult) -> RunResult:
        self.end_events()
        self.executions.clear()
        self._results.setdefault(self.root_context.execution_id, root)
        totals = {
            name: sum(getattr(result.usage, name) for result in self._results.values())
            for name in TokenUsage.model_fields
        }
        self.result = RunResult(
            self.run_id,
            self.conversation_id,
            root,
            TokenUsage(**totals),
            tuple(self._artifacts),
            tuple(self._results.items()),
        )
        self.completed = True
        for waiter in tuple(self.waiters):
            waiter.set()
        return self.result

    def snapshot(self) -> RunSnapshot:
        return RunSnapshot(
            self.run_id, self.conversation_id, len(self.records), self.result.status if self.result else "running"
        )

    def events(self, after_seq: int = 0) -> AsyncGenerator[SequencedEvent, None]:
        if after_seq < 0 or after_seq > len(self.records):
            raise InvalidRunCursorError(f"Cursor {after_seq} is invalid for run '{self.run_id}'")
        return self._iterate(after_seq)

    async def _iterate(self, after_seq: int) -> AsyncGenerator[SequencedEvent, None]:
        wake = asyncio.Event()
        self.waiters.add(wake)
        next_seq = after_seq + 1
        try:
            while True:
                wake.clear()
                while next_seq <= len(self.records):
                    record = self.records[next_seq - 1]
                    next_seq += 1
                    yield record
                if self.completed:
                    return
                await wake.wait()
        finally:
            self.waiters.discard(wake)
