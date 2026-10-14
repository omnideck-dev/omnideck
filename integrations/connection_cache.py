"""Application-owned discovery polling; readers never perform supervisor I/O."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from integrations.operation_grants import OperationGrants
from integrations.service import IntegrationService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntegrationConnection:
    """Immutable, non-secret connection projection used for tool discovery."""

    id: str
    slug: str
    kind: str = "integration"
    operation_grants: OperationGrants = frozenset()
    state: str = "running"


ConnectionSnapshot = tuple[IntegrationConnection, ...]


class IntegrationConnectionCache:
    """Poll one service and publish immutable snapshots on the application loop.

    The owner must start and close this service. A failed poll publishes an
    unavailable/empty snapshot for new runs; snapshots already held by runs
    remain unchanged. No credentials or persisted state belong here.
    """

    def __init__(
        self, service: IntegrationService, *, poll_interval: float = 5.0,
        request_timeout: float = 5.0,
    ) -> None:
        if poll_interval <= 0 or request_timeout <= 0:
            raise ValueError("Polling interval and request timeout must be positive")
        self._service = service
        self._poll_interval = poll_interval
        self._request_timeout = request_timeout
        self._snapshot: ConnectionSnapshot = ()
        self._available = False
        self._loaded = asyncio.Event()
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._closed = False
        self._waiters: list[asyncio.Future[bool]] = []

    @property
    def available(self) -> bool:
        return self._available

    def snapshot(self) -> ConnectionSnapshot:
        """Read locally; retaining the result freezes discovery for a run."""
        return self._snapshot

    def start(self) -> None:
        """Start the single poller, including an immediate initial fetch."""
        if self._closed:
            raise RuntimeError("Integration connection cache is closed")
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="integration-connections")

    async def wait_loaded(self) -> None:
        """Wait for the first successful snapshot (including an empty one)."""
        await self._loaded.wait()

    def request_refresh(self) -> None:
        """Wake the poller; requests during a fetch trigger a subsequent fetch."""
        if self._task is None:
            raise RuntimeError("Integration connection cache is not started")
        self._wake.set()

    async def refresh(self) -> bool:
        """Wait for a fetch started after this request; failure returns False.

        Call after a successful mutation so an older in-flight list cannot
        satisfy the refresh. Cancelling a caller does not cancel the poller.
        """
        if self._task is None:
            raise RuntimeError("Integration connection cache is not started")
        waiter: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._waiters.append(waiter)
        self.request_refresh()
        try:
            return await waiter
        finally:
            if waiter in self._waiters:
                self._waiters.remove(waiter)

    async def close(self) -> None:
        """Cancel and await polling, including any outstanding supervisor call."""
        task = self._task
        self._closed = True
        self._task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for waiter in self._waiters:
            if not waiter.done():
                waiter.cancel()
        self._waiters.clear()
        self._snapshot = ()
        self._available = False
        self._loaded.clear()

    async def _run(self) -> None:
        active_waiters: list[asyncio.Future[bool]] = []
        try:
            while True:
                # Clear before I/O, never after: a wake during the fetch must
                # survive and cause another fetch before we go back to sleep.
                self._wake.clear()
                active_waiters, self._waiters = self._waiters, []
                await self._poll()
                for waiter in active_waiters:
                    if not waiter.done():
                        waiter.set_result(self._available)
                active_waiters = []
                try:
                    await asyncio.wait_for(self._wake.wait(), self._poll_interval)
                except TimeoutError:
                    pass
        finally:
            for waiter in [*active_waiters, *self._waiters]:
                if not waiter.done():
                    waiter.cancel()
            self._waiters.clear()

    async def _poll(self) -> None:
        try:
            async with asyncio.timeout(self._request_timeout):
                entries = await self._service.list_connections()
            snapshot = _project_connections(entries)
        except Exception as exc:  # noqa: BLE001
            # Fail closed, but keep retrying even after malformed responses.
            logger.warning("Integration discovery unavailable (%s)", type(exc).__name__)
            self._snapshot = ()
            self._available = False
            return
        self._snapshot = snapshot
        self._available = True
        self._loaded.set()


def _project_connections(entries: list[dict]) -> ConnectionSnapshot:
    result = []
    for entry in entries:
        connection_id, slug = entry.get("id"), entry.get("slug")
        grants = entry.get("operation_grants", [])
        state, kind = entry.get("state"), entry.get("kind", "integration")
        if (
            not isinstance(connection_id, str) or not isinstance(slug, str)
            or not isinstance(state, str) or not isinstance(kind, str)
            or not isinstance(grants, list) or any(not isinstance(g, str) for g in grants)
        ):
            raise ValueError("Malformed integration discovery record")
        result.append(IntegrationConnection(connection_id, slug, kind, frozenset(grants), state))
    return tuple(result)
