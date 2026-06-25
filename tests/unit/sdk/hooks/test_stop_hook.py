"""Tests for StopHook."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sdk.events import reset_current_conversation, set_current_conversation
from sdk.hooks import StopHook
from sdk.turn import StopRequestedError


async def test_after_model_stop_clears_tool_calls_without_publishing() -> None:
    """A stop after the model responds must prevent the pending tool calls
    from running, without fabricating any event — a synthetic 'user requested
    stop' user_message would persist into the event log, render as a fake
    user bubble, and feed into the LLM history on every later turn."""
    hook = StopHook()
    history: list[dict[str, Any]] = []
    response = SimpleNamespace(
        message=SimpleNamespace(
            tool_calls=[{"function": {"name": "write_file", "arguments": "{}"}}],
        ),
    )

    # Bind a spy conversation so any publish_event would be observable.
    conv = MagicMock()
    token = set_current_conversation(conv)
    try:
        with patch("sdk.hooks._stop_hook.check_stop", side_effect=StopRequestedError):
            with pytest.raises(StopRequestedError):
                await hook.after_model(response, history, 1, "TEST")
    finally:
        reset_current_conversation(token)

    assert response.message.tool_calls is None
    conv.add_event.assert_not_called()


async def test_after_model_passes_response_through_without_stop() -> None:
    """No stop requested: the response is returned untouched."""
    hook = StopHook()
    response = SimpleNamespace(message=SimpleNamespace(tool_calls=None))

    result = await hook.after_model(response, [], 1, "TEST")

    assert result is response
