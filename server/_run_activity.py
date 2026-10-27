"""Lightweight activity projection over accepted runs and their existing results."""

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Literal, TypedDict

from aiohttp import web

from agent_runtime import AgentRuntime, RunHandle
from server._agent_runtime import AGENT_RUNTIME_KEY


_ACTIVITY_QUEUE_LIMIT = 128
_ACTIVITY_WRITE_TIMEOUT_SECONDS = 30


class _ActivityBacklogExceeded(Exception):
    """The subscriber fell behind and must reconnect for a fresh snapshot."""


class RunIdentity(TypedDict):
    conversation_id: str
    run_id: str


class RunActivity(TypedDict):
    type: Literal["snapshot", "started", "finished"]
    runs: list[RunIdentity]


def _identity(handle: RunHandle) -> RunIdentity:
    return {"conversation_id": handle.conversation_id, "run_id": handle.run_id}


async def activity_events(runtime: AgentRuntime) -> AsyncGenerator[RunActivity | None, None]:
    """Project active handles and completion into identities without retaining history."""
    queue: asyncio.Queue[RunActivity] = asyncio.Queue(maxsize=_ACTIVITY_QUEUE_LIMIT)
    overflowed = False
    watchers: set[asyncio.Task[None]] = set()

    def enqueue(event: RunActivity) -> bool:
        nonlocal overflowed
        if overflowed:
            return False
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            overflowed = True
            return False
        return True

    async def follow(handle: RunHandle) -> None:
        await handle.wait()
        enqueue({"type": "finished", "runs": [_identity(handle)]})

    def watch(handle: RunHandle) -> None:
        task = asyncio.create_task(follow(handle))
        watchers.add(task)
        task.add_done_callback(watchers.discard)

    def started(handle: RunHandle) -> None:
        if enqueue({"type": "started", "runs": [_identity(handle)]}):
            watch(handle)

    with runtime.observe_runs(started) as active:
        try:
            for handle in active:
                watch(handle)
            yield {"type": "snapshot", "runs": [_identity(handle) for handle in active]}
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
            pending = tuple(watchers)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)


async def run_activity_handler(request: web.Request) -> web.StreamResponse:
    """Send the current active runs, then start and finish updates over SSE."""
    response = web.StreamResponse(headers={
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })
    await response.prepare(request)
    events = activity_events(request.app[AGENT_RUNTIME_KEY])
    try:
        async for event in events:
            frame = f"data: {json.dumps(event)}\n\n" if event is not None else ": keepalive\n\n"
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
