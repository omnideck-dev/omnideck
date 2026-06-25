"""NudgeHook — drains queued nudge messages and injects them into history."""

from __future__ import annotations

import logging
from typing import Any

from sdk.events import (
    AgentEvent,
    UserMessagePayload,
    get_current_agent_id,
    publish_event,
)
from sdk.turn import drain_nudges

logger = logging.getLogger(__name__)


class NudgeHook:
    """Drains queued nudge messages and injects them into the conversation history.

    Each agent has its own nudge queue keyed by agent ID. The hook drains
    the current agent's queue before each model call.
    """

    async def before_model(self, history: Any, iteration: int, agent_name: str) -> None:
        """Publish any queued nudge messages as a user message event."""
        nudges = drain_nudges(get_current_agent_id())
        if nudges:
            combined = "\n\n".join(nudges)
            try:
                publish_event(AgentEvent(payload=UserMessagePayload(
                    type="user_message", content=combined, is_nudge=True,
                )))
            except Exception:  # pragma: no cover - defensive
                logger.exception("Failed to publish nudge user_message event")
            logger.info("Injected %d nudge(s) for agent '%s'", len(nudges), agent_name)
