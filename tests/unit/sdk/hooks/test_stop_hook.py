"""Tests for StopHook."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sdk.hooks import StopHook
from sdk.turn import StopRequestedError


class _FakeHistory:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def append(self, msg: dict[str, Any]) -> None:
        self.messages.append(msg)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_after_model_stop_clears_tool_calls_without_appending_history() -> None:
    """A stop after model response should prevent tools without fake transcript messages."""
    hook = StopHook()
    history = _FakeHistory()
    response = SimpleNamespace(
        message=SimpleNamespace(
            tool_calls=[{"function": {"name": "write_file", "arguments": "{}"}}],
        ),
    )

    with patch("sdk.hooks._stop_hook.check_stop", side_effect=StopRequestedError):
        with pytest.raises(StopRequestedError):
            await hook.after_model(response, history, 1, "TEST")

    assert response.message.tool_calls is None
    assert history.messages == []
