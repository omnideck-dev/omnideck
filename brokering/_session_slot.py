"""Active broker session ownership and cleanup; no draining or automatic retries."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from typing import Generic, TypeVar

from brokering._control import PreparedBrokerSession

T = TypeVar("T")


class BrokerSessionSlot(Generic[T]):
    """Own the active broker session and prepare replacements without touching it.

    A session is provider-specific runtime state, not a saved connection record
    or necessarily a network connection. Integration factories yield dispatchers
    with clients; the LLM proxy yields credentials/configuration. There is no
    common session base class: this slot only manages their shared lifetime.

    ``create_session`` returns an async context manager. Entering it prepares
    the session; exiting it releases that session's resources. The yielded
    object needs no close method. ``PreparedBrokerSession`` retains the cleanup
    callbacks until the caller activates or discards it exactly once.

    Factories must clean up partially constructed candidates on failure. On
    activation, new calls see the replacement immediately; closing the old
    session may interrupt existing calls. Nothing retries those calls.
    """

    def __init__(self, create_session: Callable[[dict[str, str]], AbstractAsyncContextManager[T]]) -> None:
        self._create_session = create_session
        self._active_session: T | None = None
        self._active_cleanup = AsyncExitStack()

    @property
    def current(self) -> T:
        """Return the active provider-specific object, never a pending candidate."""
        if self._active_session is None:
            raise RuntimeError("broker session not initialized")
        return self._active_session

    async def prepare(self, connection_fields: dict[str, str]) -> PreparedBrokerSession:
        """Create a candidate from credentials/configuration, leaving current unchanged."""
        candidate_cleanup = AsyncExitStack()
        try:
            candidate = await candidate_cleanup.enter_async_context(self._create_session(connection_fields))
        except BaseException:
            await candidate_cleanup.aclose()
            raise

        async def activate() -> None:
            previous_cleanup = self._active_cleanup
            # Publish before retiring the previous session. If cleanup fails,
            # activation is ambiguous; the supervisor must stop this broker.
            self._active_session, self._active_cleanup = candidate, candidate_cleanup
            await previous_cleanup.aclose()

        return PreparedBrokerSession(activate=activate, discard=candidate_cleanup.aclose)

    async def close(self) -> None:
        """Release the active session; pending candidates belong to BrokerControl."""
        await self._active_cleanup.aclose()
        self._active_session = None
