"""Event observer that indexes file_output events into the artifacts store."""

from __future__ import annotations

import logging

from sdk.events import AgentEvent

from ._store import record_artifact

logger = logging.getLogger(__name__)


class ArtifactsIndexWriter:
    """Subscribes to a conversation's events and records each file sent.

    Mirrors the per-turn disk writers: construct with the conversation id,
    subscribe ``handle_event``, unsubscribe when the turn ends. Synchronous, so
    the event loop serializes its writes to the shared index.
    """

    def __init__(self, conversation_id: str) -> None:
        self._conversation_id = conversation_id

    def handle_event(self, event: AgentEvent) -> None:
        """Record file_output events; ignore everything else. Never raises."""
        payload = event.payload
        if payload.type != "file_output":
            return
        # Legacy base64-only outputs carry no path — nothing to index or
        # reconcile against disk, so skip them.
        if not payload.path:
            return
        try:
            record_artifact(
                conversation_id=self._conversation_id,
                path=payload.path,
                filename=payload.filename,
                content_type=payload.content_type,
                agent_name=event.agent_name,
                sent_at=event.timestamp.isoformat(),
            )
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "Failed to index artifact (conversation=%s, path=%s)",
                self._conversation_id,
                payload.path,
            )
