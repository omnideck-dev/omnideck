"""One scheduler for durable work supplied by domain-owned stores."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScheduledWork:
    """A durable identity and due time; dispatch claims/revalidates its saved state.

    Dispatch returns the admitted execution's completion future, or None when
    the target became unavailable. The source owns cancellation of that future.
    """
    id: str
    target: str
    due_at: datetime
    labels: dict[str, str]
    dispatch: Callable[[], Awaitable[asyncio.Future | None]]


class WorkSource(Protocol):
    name: str

    @property
    def enabled(self) -> bool: ...

    def recover(self) -> None: ...

    def pending(self, now: datetime) -> Sequence[ScheduledWork]: ...


@dataclass
class RunningWork:
    source: str
    work: ScheduledWork
    completion: asyncio.Future


class Scheduler:
    """Poll sources, share capacity fairly, and serialize admission and cleanup.

    Schedules remain in source stores, avoiding a second persistent queue that
    could disagree with a changed goal or routine. This is a single-process
    service, like the AgentRuntime it feeds.
    """
    def __init__(self, *, max_concurrent: int, poll_interval: float, shutdown_timeout: float) -> None:
        if max_concurrent < 1 or poll_interval <= 0 or shutdown_timeout < 0:
            raise ValueError("Invalid scheduler limits")
        self.max_concurrent = max_concurrent
        self._poll_interval = poll_interval
        self._shutdown_timeout = shutdown_timeout
        self._sources: dict[str, WorkSource] = {}
        self._running: dict[tuple[str, str], RunningWork] = {}
        self._blocked: set[tuple[str, str, str]] = set()
        self._tick_lock = asyncio.Lock()
        self._control_lock = asyncio.Lock()
        self._stopping = asyncio.Event()
        self._woken = asyncio.Event()
        self._loop_task: asyncio.Task | None = None
        self._next_source = 0

    def register(self, source: WorkSource) -> None:
        if self._loop_task is not None or source.name in self._sources:
            raise ValueError("Register each work source once, before scheduler startup")
        self._sources[source.name] = source

    @property
    def running(self) -> bool:
        return self._loop_task is not None and not self._loop_task.done() and not self._stopping.is_set()

    async def start(self) -> None:
        if self._stopping.is_set():
            raise RuntimeError("The scheduler has stopped")
        if self._loop_task is not None:
            return
        for source in self._sources.values():
            source.recover()
        self._loop_task = asyncio.create_task(self._poll(), name="scheduled-work")

    def active(self, source: str) -> list[RunningWork]:
        self._prune()
        return [entry for entry in self._running.values() if entry.source == source]

    def blocked(self, source: str, labels: dict[str, str]) -> bool:
        return any((source, key, value) in self._blocked for key, value in labels.items())

    def _prune(self) -> None:
        for key, entry in list(self._running.items()):
            if entry.completion.done():
                del self._running[key]
                if not entry.completion.cancelled():
                    error = entry.completion.exception()
                    if error is not None:
                        logger.error("Scheduled work %s failed: %s", key, error)

    async def tick(self, now: datetime | str | None = None) -> None:
        instant = datetime.fromisoformat(now) if isinstance(now, str) else now or datetime.now(timezone.utc)
        if instant.tzinfo is None:
            raise ValueError("Scheduler time must include a timezone")
        async with self._tick_lock:
            if self._stopping.is_set():
                return
            self._prune()
            sources = list(self._sources.values())
            if not sources:
                return
            # Rotate after each admission so a busy source cannot consume every
            # newly available slot while another source waits.
            start = self._next_source % len(sources)
            ordered = sources[start:] + sources[:start]
            queues = []
            for source in ordered:
                if not source.enabled:
                    continue
                try:
                    candidates = sorted(source.pending(instant), key=lambda work: work.due_at)
                    queues.append((source, iter(candidates)))
                except Exception:
                    logger.exception("Could not read scheduled work from %s", source.name)
            while queues and len(self._running) < self.max_concurrent:
                remaining = []
                for source, jobs in queues:
                    if self._stopping.is_set() or len(self._running) >= self.max_concurrent:
                        break
                    work = next(jobs, None)
                    if work is None:
                        continue
                    remaining.append((source, jobs))
                    key = (source.name, work.id)
                    if (not source.enabled or work.due_at > instant or key in self._running
                            or self.blocked(source.name, work.labels)
                            or any(entry.work.target == work.target for entry in self._running.values())):
                        continue
                    try:
                        completion = await work.dispatch()
                    except Exception:
                        logger.exception("Could not dispatch scheduled work %s", key)
                        continue
                    if completion is not None:
                        self._running[key] = RunningWork(source.name, work, completion)
                        self._next_source = (sources.index(source) + 1) % len(sources)
                queues = remaining

    @asynccontextmanager
    async def block(self, source: str, label: str, value: str) -> AsyncIterator[None]:
        """Stop matching work and hold admission until destructive cleanup ends."""
        async with self._control_lock:
            async with self._tick_lock:
                key = (source, label, value)
                self._blocked.add(key)
                tasks = [entry.completion for entry in self.active(source) if entry.work.labels.get(label) == value]
            try:
                await self._cancel(tasks)
                yield
            finally:
                self._prune()
                self._blocked.remove(key)

    @staticmethod
    async def _cancel(tasks: Sequence[asyncio.Future]) -> None:
        for task in tasks:
            # A second cancellation could interrupt execution-tree cleanup.
            if not task.done() and (not isinstance(task, asyncio.Task) or not task.cancelling()):
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def stop(self) -> None:
        self._stopping.set()
        if self._loop_task is not None:
            await self._loop_task
        # Wait for an in-flight admission before taking the shutdown snapshot.
        async with self._tick_lock:
            tasks = [entry.completion for entry in self._running.values()]
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=self._shutdown_timeout)
            await self._cancel(list(pending))
        self._prune()

    def wake(self) -> None:
        """Check sources now instead of at the next poll, such as after a schedule changes."""
        self._woken.set()

    async def _poll(self) -> None:
        while not self._stopping.is_set():
            self._woken.clear()
            try:
                await self.tick()
            except Exception:
                logger.exception("Scheduled work tick failed")
            waiters = [asyncio.ensure_future(self._stopping.wait()), asyncio.ensure_future(self._woken.wait())]
            try:
                await asyncio.wait(waiters, timeout=self._poll_interval, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for waiter in waiters:
                    waiter.cancel()
                await asyncio.gather(*waiters, return_exceptions=True)
