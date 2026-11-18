"""App-wide activity stream: run starts and finishes, plus feature feeds such as goals."""

import asyncio
from collections.abc import AsyncGenerator, Callable, Sequence
from typing import Protocol

from aiohttp import web

from agent_runtime import AgentRuntime, RunHandle
from server._activity_messages import (
    ActivityMessage, RunFinishedMessage, RunIdentity, RunSnapshotMessage, RunStartedMessage,
)
from server._agent_runtime import AGENT_RUNTIME_KEY


_ACTIVITY_QUEUE_LIMIT = 128
_ACTIVITY_WRITE_TIMEOUT_SECONDS = 30


class ActivityFeed(Protocol):
    """A feature's messages on the activity stream."""

    def subscribe(self, send: Callable[[ActivityMessage], bool]) -> Callable[[], None]: ...

    def snapshot(self) -> ActivityMessage | None: ...


ACTIVITY_FEEDS_KEY: web.AppKey[list[ActivityFeed]] = web.AppKey("activity_feeds", list)


class _ActivityBacklogExceeded(Exception):
    """The subscriber fell behind and must reconnect for a fresh snapshot."""


def _identity(handle: RunHandle) -> RunIdentity:
    return RunIdentity(conversation_id=handle.conversation_id, run_id=handle.run_id)


async def activity_events(
    runtime: AgentRuntime, feeds: Sequence[ActivityFeed] = (),
) -> AsyncGenerator[ActivityMessage | None, None]:
    """Project active runs and feature feeds into messages without retaining history."""
    queue: asyncio.Queue[ActivityMessage] = asyncio.Queue(maxsize=_ACTIVITY_QUEUE_LIMIT)
    overflowed = False
    watchers: set[asyncio.Task[None]] = set()
    unsubscribes: list[Callable[[], None]] = []

    def enqueue(message: ActivityMessage) -> bool:
        nonlocal overflowed
        if overflowed:
            return False
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            overflowed = True
            return False
        return True

    async def follow(handle: RunHandle) -> None:
        await handle.wait()
        enqueue(RunFinishedMessage(type="run_finished", runs=[_identity(handle)]))

    def watch(handle: RunHandle) -> None:
        task = asyncio.create_task(follow(handle))
        watchers.add(task)
        task.add_done_callback(watchers.discard)

    def started(handle: RunHandle) -> None:
        if enqueue(RunStartedMessage(type="run_started", runs=[_identity(handle)])):
            watch(handle)

    with runtime.observe_runs(started) as active:
        try:
            unsubscribes.extend(feed.subscribe(enqueue) for feed in feeds)
            snapshots = [feed.snapshot() for feed in feeds]
            for handle in active:
                watch(handle)
            yield RunSnapshotMessage(type="run_snapshot", runs=[_identity(handle) for handle in active])
            for snapshot in snapshots:
                if snapshot is not None:
                    yield snapshot
            while True:
                if overflowed:
                    # Do not deliver an incomplete history. Reconnection reconciles
                    # the browser's known runs against a new active-run snapshot.
                    raise _ActivityBacklogExceeded
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    # Keep idle connections alive and detect disconnected observers.
                    yield None
        finally:
            for unsubscribe in unsubscribes:
                unsubscribe()
            pending = tuple(watchers)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)


async def run_activity_handler(request: web.Request) -> web.StreamResponse:
    """Send the current state, then run and feature updates over SSE."""
    response = web.StreamResponse(headers={
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })
    await response.prepare(request)
    events = activity_events(request.app[AGENT_RUNTIME_KEY], request.app.get(ACTIVITY_FEEDS_KEY, []))
    try:
        async for message in events:
            frame = f"data: {message.model_dump_json()}\n\n" if message is not None else ": keepalive\n\n"
            async with asyncio.timeout(_ACTIVITY_WRITE_TIMEOUT_SECONDS):
                await response.write(frame.encode())
    except (ConnectionResetError, TimeoutError, _ActivityBacklogExceeded):
        response.force_close()
        # Closing the socket also prevents final response flushing from stalling.
        if request.transport is not None:
            request.transport.close()
    finally:
        await events.aclose()
    return response
