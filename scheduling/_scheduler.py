"""One scheduler for durable work supplied by domain-owned stores."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
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
    """Poll sources and admit each source's due work within its own run limit.

    Sources share only the poll loop, the clock, admission and shutdown.
    Schedules remain in source stores, avoiding a second persistent queue that
    could disagree with a changed goal or routine. This is a single-process
    service, like the AgentRuntime it feeds.
    """
    def __init__(self, *, limits: Mapping[str, int], poll_interval: float, shutdown_timeout: float) -> None:
        if any(limit < 1 for limit in limits.values()) or poll_interval <= 0 or shutdown_timeout < 0:
            raise ValueError("Invalid scheduler limits")
        self.limits = limits
        self._poll_interval = poll_interval
        self._shutdown_timeout = shutdown_timeout
        self._sources: dict[str, WorkSource] = {}
        self._running: dict[tuple[str, str], RunningWork] = {}
        self._tick_lock = asyncio.Lock()
        self._stopping = asyncio.Event()
        self._woken = asyncio.Event()
        self._loop_task: asyncio.Task | None = None

    def register(self, source: WorkSource) -> None:
        if self._loop_task is not None or source.name in self._sources:
            raise ValueError("Register each work source once, before scheduler startup")
        if source.name not in self.limits:
            raise ValueError(f"Scheduled work source '{source.name}' has no run limit")
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
            try:
                source.recover()
            except Exception:
                logger.exception("Could not recover scheduled work from %s", source.name)
        self._loop_task = asyncio.create_task(self._poll(), name="scheduled-work")

    def active(self, source: str) -> list[RunningWork]:
        self._prune()
        return [entry for entry in self._running.values() if entry.source == source]

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
            limits = dict(self.limits)
            for source in self._sources.values():
                if not source.enabled:
                    continue
                try:
                    candidates = sorted(source.pending(instant), key=lambda work: work.due_at)
                except Exception:
                    logger.exception("Could not read scheduled work from %s", source.name)
                    continue
                for work in candidates:
                    if self._stopping.is_set() or len(self.active(source.name)) >= limits[source.name]:
                        break
                    key = (source.name, work.id)
                    if (not source.enabled or work.due_at > instant or key in self._running
                            or any(entry.work.target == work.target for entry in self._running.values())):
                        continue
                    try:
                        completion = await work.dispatch()
                    except Exception:
                        logger.exception("Could not dispatch scheduled work %s", key)
                        continue
                    if completion is not None:
                        self._running[key] = RunningWork(source.name, work, completion)

    @staticmethod
    async def _cancel(tasks: Sequence[asyncio.Future]) -> None:
        for task in tasks:
            if not task.done() and (not isinstance(task, asyncio.Task) or not task.cancelling()):
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def stop(self) -> None:
        self._stopping.set()
        if self._loop_task is not None:
            await self._loop_task
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
