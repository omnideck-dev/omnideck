"""Conversation history derived from an append-only event log.

The history surface other code sees — ``messages``, ``system_message``,
``non_system_messages`` — is computed on demand from two pieces of
state:

- ``_system_message``: the system prompt currently active for this
  agent. Held outside the event log because the system prompt is
  refreshed every turn from agent + skill state rather than being a
  recorded interaction.
- ``_events``: the in-memory copy of the persisted events.jsonl log.
  Populated at construction by ``seed_events`` and kept in sync with
  the live dispatcher by ``handle_event``.

``derived_messages`` runs ``build_llm_view`` against ``_events`` to
produce the LLM-shaped message list for this agent. Callers who used
to read ``messages`` see the same dict shape; callers who used to
mutate via ``append`` / ``drop_range`` / ``insert`` publish events
instead and let the next read derive the new view.
"""

import asyncio
import logging
from collections.abc import Callable, Iterator
from contextlib import suppress
from inspect import iscoroutinefunction
from typing import Any

from agent_core.events._models import AgentEvent

from ._view import build_llm_view, events_for_agent

logger = logging.getLogger(__name__)

# Event types the in-memory log retains. This serves two readers: the
# derived LLM/transcript view (which only reads message-shaped types) and
# the warm-resume path, which replays this same in-memory log to restore the
# UI. So it must hold every type resume replays — file_output (inline file
# blocks) and spawn_requested (sub-agent cards) included — or a conversation
# resumed from the warm cache loses them while a cold disk resume keeps them.
_RETAINED_EVENT_TYPES: frozenset[str] = frozenset({
    "user_message",
    "iteration",
    "tool_result",
    "compaction",
    "agent_started",
    "agent_completed",
    "file_output",
    "spawn_requested",
})


class ConversationHistory:
    """LLM message history as a view over an event log."""

    def __init__(
        self,
        system_message: str | None = None,
        *,
        conversation_id: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        # The system message is the one part of the LLM view that isn't an
        # event; everything else is reconstructed from the event log.
        self._system_message: dict[str, Any] | None = (
            {"role": "system", "content": system_message} if system_message else None
        )
        self._conversation_id = conversation_id
        # None = root view (depth-0 agents only). Set explicitly for sub-agents.
        self._agent_id = agent_id
        self._events: list[dict[str, Any]] = []
        # Observers fan-out: disk writer, SSE stream, future webhooks, etc.
        # The conversation IS the canonical state, not a subscriber, so the
        # observer list never includes the conversation's own append.
        self._observers: list[Callable[[AgentEvent], Any]] = []
        self._async_obs_tasks: set[asyncio.Task[Any]] = set()

    # -- read-only access --------------------------------------------------

    @property
    def messages(self) -> list[dict[str, Any]]:
        """LLM-ready message list: system message + derived conversation."""
        body = self.derived_messages
        if self._system_message is None:
            return body
        return [dict(self._system_message), *body]

    @property
    def system_message(self) -> dict[str, Any] | None:
        """The active system message, or None."""
        if self._system_message is None:
            return None
        return dict(self._system_message)

    @property
    def non_system_messages(self) -> list[dict[str, Any]]:
        """Derived message list excluding the system message."""
        return self.derived_messages

    @property
    def derived_messages(self) -> list[dict[str, Any]]:
        """Reconstruct the LLM message list from the recorded events."""
        if self._conversation_id is None:
            return []
        return build_llm_view(self._events, agent_filter=self._agent_id)

    @property
    def recorded_events(self) -> list[dict[str, Any]]:
        """Snapshot of the in-memory event log used for the derived view."""
        return list(self._events)

    @property
    def scoped_events(self) -> list[dict[str, Any]]:
        """The events that make up *this* history's thread.

        Same membership the derived message view uses (root view for the
        root history, exact agent_id for a sub-agent). Used by compaction
        to resolve kept bounds so it counts the right iterations.
        """
        if self._conversation_id is None:
            return []
        return events_for_agent(self._events, self._agent_id)

    # -- mutation ----------------------------------------------------------

    def set_system_message(self, content: str) -> None:
        """Replace or set the system message."""
        self._system_message = {"role": "system", "content": content}

    def seed_events(self, events: list[dict[str, Any]]) -> None:
        """Replace the in-memory event log with *events*.

        Used at construction / resume time to populate from disk before
        live events start arriving via ``handle_event``.
        """
        self._events = list(events)

    def add_event(self, event: AgentEvent) -> None:
        """Canonical write: append + fan out to observers.

        Synchronously updates the in-memory event log for retained event
        types (so the next read of ``messages`` — and a warm resume — reflects
        this event), then notifies every observer. Observers receive every
        event regardless of type; persistence and the UI stream also handle
        types the in-memory log doesn't retain.
        """
        if self._conversation_id is not None and event.payload.type in _RETAINED_EVENT_TYPES:
            self._events.append(event.to_flat_dict(self._conversation_id))
        for obs in tuple(self._observers):
            try:
                if iscoroutinefunction(obs):
                    task = asyncio.create_task(self._run_async_observer(obs, event))
                    self._async_obs_tasks.add(task)
                    task.add_done_callback(self._async_obs_tasks.discard)
                else:
                    obs(event)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Conversation observer failed")

    def subscribe(self, handler: Callable[[AgentEvent], Any]) -> None:
        """Attach an observer that receives every event added to this conversation.

        Observers can be sync or async; async ones are scheduled on the loop.
        Idempotent — subscribing the same handler twice is a no-op.
        """
        if handler not in self._observers:
            self._observers.append(handler)

    def unsubscribe(self, handler: Callable[[AgentEvent], Any]) -> None:
        """Detach a previously-subscribed observer. Idempotent."""
        with suppress(ValueError):
            self._observers.remove(handler)

    async def drain_observers(self) -> None:
        """Wait for any in-flight async observer tasks to finish."""
        if not self._async_obs_tasks:
            return
        pending = tuple(self._async_obs_tasks)
        try:
            for task in pending:
                try:
                    await asyncio.shield(task)
                except Exception:  # pragma: no cover - handler logs already
                    logger.exception("Unhandled exception while draining observer")
        except asyncio.CancelledError:
            # The execution owner is shutting down. Shielding the drain must
            # not leave detached writers running after session completion.
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            raise

    async def _run_async_observer(
        self, handler: Callable[[AgentEvent], Any], event: AgentEvent,
    ) -> None:
        try:
            await handler(event)
        except Exception:  # pragma: no cover - logged
            logger.exception("Unhandled exception in async observer")

    def handle_event(self, event: AgentEvent) -> None:
        """Backwards-compatible alias for ``add_event``.

        Old code subscribed ``handle_event`` to a dispatcher. New code calls
        ``add_event`` directly and subscribes other observers to the
        conversation.
        """
        self.add_event(event)

    # -- dunder helpers ----------------------------------------------------

    def __len__(self) -> int:
        return len(self.messages)

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.messages)

    def __repr__(self) -> str:
        return "ConversationHistory(len=%d)" % len(self.messages)
