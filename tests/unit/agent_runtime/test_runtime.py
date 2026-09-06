"""Unit tests for process-scoped active agent run ownership."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from sdk.turn import ExecutionResult
from agent_runtime import RunSession

from agent_runtime import (
    RunConflictError,
    AgentRuntime,
    AgentRuntimeClosedError,
    AgentRunRequest,
    InvalidRunCursorError,
    SequencedEvent,
)
from sdk.events import (
    AgentEvent,
    ContentPayload,
    ErrorPayload,
    TurnEndPayload,
)


def _request(conversation_id: str = "conversation-1") -> AgentRunRequest:
    return AgentRunRequest(
        conversation_id=conversation_id,
        message="hello",
        attachments=None,
        profile_id="profile-1",
    )


def _content(event_id: str, text: str) -> AgentEvent:
    return AgentEvent(
        id=event_id,
        payload=ContentPayload(type="content", content=text, delta=True),
    )


def _error(event_id: str, message: str) -> AgentEvent:
    return AgentEvent(
        id=event_id,
        payload=ErrorPayload(type="error", message=message),
    )


def _turn_end(event_id: str = "event-end") -> AgentEvent:
    return AgentEvent(
        id=event_id,
        payload=TurnEndPayload(type="turn_end"),
    )


RunnerCallback = Callable[
    [AgentRunRequest, Callable[[AgentEvent], None], asyncio.Event],
    Awaitable[None],
]


class CallbackRunner:
    """Adapt a test coroutine to the manager's runner seam."""

    def __init__(self, callback: RunnerCallback) -> None:
        self._callback = callback

    async def run(
        self,
        request: AgentRunRequest,
        session: RunSession,
    ) -> ExecutionResult:
        await self._callback(request, session.add_event, session.stop_event)
        return ExecutionResult("success")


class ControlledRunner:
    """Fake runner whose event publication and completion are test-controlled."""

    def __init__(self) -> None:
        """Create synchronization points used by manager tests."""
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.emit_event: Callable[[AgentEvent], None] | None = None
        self.stop_event: asyncio.Event | None = None
        self.stop_was_set_on_start: bool | None = None

    async def run(
        self,
        request: AgentRunRequest,
        session: RunSession,
    ) -> ExecutionResult:
        """Capture manager-owned controls and wait for test release."""
        emit = session.add_event
        stop_event = session.stop_event
        assert request.profile_id == "profile-1"
        assert request.conversation_id
        self.emit_event = emit
        self.stop_event = stop_event
        self.stop_was_set_on_start = stop_event.is_set()
        self.started.set()
        try:
            await self.release.wait()
            return ExecutionResult("success")
        except asyncio.CancelledError:
            self.cancelled.set()
            raise

    def emit(self, event: AgentEvent) -> None:
        """Publish one event through the callback supplied by the manager."""
        assert self.emit_event is not None
        self.emit_event(event)


async def _collect_stream(stream) -> list[SequencedEvent]:
    return [record async for record in stream]


async def test_disconnect_only_closes_subscriber_and_runner_keeps_running() -> None:
    """Closing a subscription must not cancel its background runner."""
    runner = ControlledRunner()
    manager = AgentRuntime(runner)
    info = await manager.start(_request())
    first_stream = info.events(after_seq=0)

    await runner.started.wait()
    runner.emit(_content("event-1", "one"))
    first = await anext(first_stream)
    assert (first.seq, first.event.id) == (1, "event-1")

    await first_stream.aclose()

    assert manager.active_for_conversation("conversation-1") is not None
    assert runner.cancelled.is_set() is False

    runner.emit(_content("event-2", "two"))
    resumed_stream = info.events(after_seq=1)
    collect_task = asyncio.create_task(_collect_stream(resumed_stream))
    runner.release.set()
    resumed = await collect_task

    assert [record.seq for record in resumed] == [2, 3]
    assert resumed[0].event.id == "event-2"
    assert resumed[-1].event.payload.type == "turn_end"
    assert manager.active_for_conversation("conversation-1") is None
    assert manager.get(info.run_id) is None


async def test_second_subscriber_gets_replay_then_live_events_in_order() -> None:
    """A later subscriber receives retained records before newly emitted ones."""
    runner = ControlledRunner()
    manager = AgentRuntime(runner)
    info = await manager.start(_request())
    initial_stream = info.events(after_seq=0)

    await runner.started.wait()
    runner.emit(_content("event-1", "one"))
    assert (await anext(initial_stream)).event.id == "event-1"

    replay_stream = info.events(after_seq=0)
    replayed = await anext(replay_stream)
    assert (replayed.seq, replayed.event.id) == (1, "event-1")

    runner.emit(_content("event-2", "two"))
    live = await anext(replay_stream)
    assert (live.seq, live.event.id) == (2, "event-2")

    await initial_stream.aclose()
    collect_task = asyncio.create_task(_collect_stream(replay_stream))
    runner.release.set()
    tail = await collect_task
    assert [record.event.payload.type for record in tail] == ["turn_end"]


async def test_event_ids_resolve_to_resume_sequences() -> None:
    """Persisted event IDs can locate the correct active-run replay cursor."""
    runner = ControlledRunner()
    manager = AgentRuntime(runner)
    info = await manager.start(_request())
    stream = info.events(after_seq=0)

    await runner.started.wait()
    runner.emit(_content("event-1", "one"))
    runner.emit(_content("event-2", "two"))

    assert info.sequence_for_event("event-1") == 1
    assert info.sequence_for_event("event-2") == 2
    assert info.sequence_for_event("missing") is None
    active = manager.active_for_conversation("conversation-1")
    assert active is not None
    assert active.snapshot().last_seq == 2

    collect_task = asyncio.create_task(_collect_stream(stream))
    runner.release.set()
    await collect_task


async def test_concurrent_starts_reserve_conversation_once() -> None:
    """Concurrent starts cannot create two runs for one conversation."""
    runner = ControlledRunner()
    manager = AgentRuntime(runner)

    results = await asyncio.gather(
        manager.start(_request()),
        manager.start(_request()),
        return_exceptions=True,
    )

    infos = [result for result in results if not isinstance(result, Exception)]
    conflicts = [result for result in results if isinstance(result, RunConflictError)]
    assert len(infos) == 1
    assert len(conflicts) == 1

    info = infos[0]
    stream = info.events(after_seq=0)
    await runner.started.wait()
    collect_task = asyncio.create_task(_collect_stream(stream))
    runner.release.set()
    await collect_task


async def test_stop_before_runner_starts_is_not_lost() -> None:
    """The manager-owned stop event records a stop before task scheduling."""
    runner = ControlledRunner()
    manager = AgentRuntime(runner)
    info = await manager.start(_request())
    stream = info.events(after_seq=0)

    info.stop()
    records = await _collect_stream(stream)
    assert runner.started.is_set() is False
    assert [r.event.payload.type for r in records] == ["turn_end"]
    assert (await info.wait()).status == "stopped"


async def test_runtime_normalizes_unexpected_runner_failure() -> None:
    """The runtime supplies an error and terminal event even for an unexpected runner failure."""

    async def failing_runner(
        _request: AgentRunRequest,
        _emit: Callable[[AgentEvent], None],
        _stop_event: asyncio.Event,
    ) -> None:
        raise RuntimeError("setup exploded")

    manager = AgentRuntime(CallbackRunner(failing_runner))
    info = await manager.start(_request())
    records = await _collect_stream(
        info.events(after_seq=0),
    )

    assert [r.event.payload.type for r in records] == ["error", "turn_end"]
    assert manager.active_for_conversation("conversation-1") is None


async def test_runner_owned_failure_events_are_not_duplicated() -> None:
    """The manager retains exactly the domain events published by its runner."""

    async def failing_runner(
        _request: AgentRunRequest,
        emit: Callable[[AgentEvent], None],
        _stop_event: asyncio.Event,
    ) -> None:
        emit(_error("event-error", "provider unavailable"))
        emit(_turn_end())
        raise RuntimeError("provider unavailable")

    manager = AgentRuntime(CallbackRunner(failing_runner))
    info = await manager.start(_request())
    records = await _collect_stream(
        info.events(after_seq=0),
    )

    assert [record.event.payload.type for record in records] == [
        "error",
        "turn_end",
    ]


async def test_normal_runner_turn_end_is_not_duplicated() -> None:
    """A successful run contains only the terminal event its runner emitted."""

    async def runner(
        _request: AgentRunRequest,
        emit: Callable[[AgentEvent], None],
        _stop_event: asyncio.Event,
    ) -> None:
        emit(_turn_end())

    manager = AgentRuntime(CallbackRunner(runner))
    info = await manager.start(_request())
    records = await _collect_stream(
        info.events(after_seq=0),
    )

    assert [record.event.payload.type for record in records] == ["turn_end"]


async def test_fast_completion_is_pruned_but_initial_subscription_finishes() -> None:
    """An initial subscriber keeps its captured run after manager pruning."""

    async def immediate_runner(
        _request: AgentRunRequest,
        _emit: Callable[[AgentEvent], None],
        _stop_event: asyncio.Event,
    ) -> None:
        return

    manager = AgentRuntime(CallbackRunner(immediate_runner))
    info = await manager.start(_request())
    stream = info.events(after_seq=0)

    records = await _collect_stream(stream)

    assert [r.event.payload.type for r in records] == ["turn_end"]
    assert manager.get(info.run_id) is None
    assert manager.get(info.run_id) is None


async def test_invalid_and_unknown_cursors_are_rejected() -> None:
    """Subscribers cannot request negative, future, or unknown cursors."""
    runner = ControlledRunner()
    manager = AgentRuntime(runner)
    info = await manager.start(_request())
    stream = info.events(after_seq=0)

    with pytest.raises(InvalidRunCursorError):
        info.events(after_seq=-1)
    with pytest.raises(InvalidRunCursorError):
        info.events(after_seq=1)
    assert manager.get("run_missing") is None

    collect_task = asyncio.create_task(_collect_stream(stream))
    runner.release.set()
    await collect_task


async def test_close_requests_stop_and_rejects_new_work() -> None:
    """Manager shutdown requests graceful stop and closes admission."""
    stopped = asyncio.Event()
    started = asyncio.Event()

    async def stop_aware_runner(
        _request: AgentRunRequest,
        _emit: Callable[[AgentEvent], None],
        stop_event: asyncio.Event,
    ) -> None:
        started.set()
        await stop_event.wait()
        stopped.set()

    manager = AgentRuntime(CallbackRunner(stop_aware_runner))
    await manager.start(_request())
    await started.wait()

    await manager.close()

    assert stopped.is_set()
    assert manager.active_for_conversation("conversation-1") is None
    with pytest.raises(AgentRuntimeClosedError):
        await manager.start(_request("conversation-2"))


async def test_close_cancels_runner_after_shutdown_timeout() -> None:
    """A runner that ignores Stop is cancelled after the shutdown deadline."""
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def stuck_runner(
        _request: AgentRunRequest,
        _emit: Callable[[AgentEvent], None],
        _stop_event: asyncio.Event,
    ) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    manager = AgentRuntime(CallbackRunner(stuck_runner), shutdown_timeout=0.001)
    await manager.start(_request())
    await started.wait()

    await manager.close()

    assert cancelled.is_set()
    assert manager.active_for_conversation("conversation-1") is None
