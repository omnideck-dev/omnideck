"""StopHook — checks for user-requested stop at before_model and after_model phases."""

from __future__ import annotations

import logging
from typing import Any

from sdk.events import AgentEvent, UserMessagePayload, publish_event
from sdk.turn import StopRequestedError, check_stop

logger = logging.getLogger(__name__)


class StopHook:
    """Checks for user-requested stop at before_model and after_model phases."""

    async def before_model(self, history: Any, iteration: int, agent_name: str) -> None:
        """Raise ``StopRequestedError`` if the user requested a stop."""
        check_stop()

    async def after_model(
        self, response: Any, history: Any, iteration: int, agent_name: str
    ) -> Any:
        """Strip tool calls and raise ``StopRequestedError`` on stop request."""
        try:
            check_stop()
        except StopRequestedError:
            # Strip tool_calls so the assistant message won't have dangling calls
            if hasattr(response, "message") and hasattr(response.message, "tool_calls"):
                response.message.tool_calls = None
            try:
                publish_event(AgentEvent(payload=UserMessagePayload(
                    type="user_message",
                    content="The user has requested to stop. Wrap up your response.",
                )))
            except Exception:  # pragma: no cover - defensive
                logger.exception("Failed to publish stop-hook event")
            raise
        return response
