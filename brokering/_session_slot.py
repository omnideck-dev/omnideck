"""Active broker sessions with leases for calls that outlive credential renewal."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Generic, TypeVar

from brokering._control import PreparedBrokerSession

T = TypeVar("T")


@dataclass(eq=False)
class _Session(Generic[T]):
    value: T
    cleanup: AsyncExitStack
    users: int = 0
    retired: bool = False


class BrokerSessionSlot(Generic[T]):
    """Publish replacements immediately; retain old transports until calls finish.

    Factories own provider cleanup. Pending candidates belong to BrokerControl;
    the slot owns activated sessions. Integration calls must borrow a lease.
    ``current`` is for synchronous control operations and immutable LLM config.
    """

    def __init__(self, create_session: Callable[[dict[str, str]], AbstractAsyncContextManager[T]]) -> None:
        self._create_session = create_session
        self._active: _Session[T] | None = None
        self._sessions: set[_Session[T]] = set()

    @property
    def current(self) -> T:
        if self._active is None:
            raise RuntimeError("broker session not initialized")
        return self._active.value

    @asynccontextmanager
    async def borrow(self) -> AsyncIterator[T]:
        session = self._active
        if session is None:
            raise RuntimeError("broker session not initialized")
        session.users += 1
        try:
            yield session.value
        finally:
            session.users -= 1
            if session.retired and session.users == 0:
                await self._release(session)

    async def _release(self, session: _Session[T]) -> None:
        try:
            await session.cleanup.aclose()
        finally:
            self._sessions.discard(session)

    async def prepare(self, connection_fields: dict[str, str]) -> PreparedBrokerSession:
        candidate_cleanup = AsyncExitStack()
        try:
            candidate = await candidate_cleanup.enter_async_context(self._create_session(connection_fields))
        except BaseException:
            await candidate_cleanup.aclose()
            raise
        session = _Session(candidate, candidate_cleanup)

        async def activate() -> None:
            previous = self._active
            self._sessions.add(session)
            self._active = session
            if previous is not None:
                previous.retired = True
                if previous.users == 0:
                    await self._release(previous)

        return PreparedBrokerSession(activate=activate, discard=candidate_cleanup.aclose)

    async def close(self) -> None:
        """Shutdown/removal closes all transports, including unfinished calls."""
        self._active = None
        async with AsyncExitStack() as cleanup:
            for session in tuple(self._sessions):
                cleanup.push_async_callback(self._release, session)
