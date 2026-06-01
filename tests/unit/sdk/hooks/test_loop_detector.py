"""Tests for LoopDetector hook."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sdk.events import UserMessagePayload
from sdk.hooks import LoopDetector


class _FakeHistory:
    """Stand-in for ConversationHistory — hooks read but never write to it."""


@pytest.fixture
def _patch_publish_event():
    """Capture publish_event calls so tests can inspect the emitted nudge."""
    with patch("sdk.hooks._loop_detector.publish_event") as mock:
        yield mock


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_action_for_different_calls(_patch_publish_event):
    detector = LoopDetector(threshold=3)
    history = _FakeHistory()
    detector.after_tool("tool_a", {"x": 1}, {"result": "ok"})
    await detector.before_model(history, 2, "TEST")
    detector.after_tool("tool_a", {"x": 2}, {"result": "ok"})
    await detector.before_model(history, 3, "TEST")
    detector.after_tool("tool_b", {"x": 1}, {"result": "ok"})
    await detector.before_model(history, 4, "TEST")
    assert _patch_publish_event.call_count == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_triggers_on_repeated_calls(_patch_publish_event):
    detector = LoopDetector(threshold=3)
    history = _FakeHistory()
    for i in range(3):
        detector.after_tool("echo", {"x": 1}, {"result": "ok"})
        await detector.before_model(history, i + 2, "TEST")
    assert _patch_publish_event.call_count == 1
    payload = _patch_publish_event.call_args[0][0].payload
    assert isinstance(payload, UserMessagePayload)
    assert "repeating" in payload.content.lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resets_after_trigger(_patch_publish_event):
    detector = LoopDetector(threshold=3)
    history = _FakeHistory()
    for i in range(3):
        detector.after_tool("echo", {"x": 1}, {"result": "ok"})
        await detector.before_model(history, i + 2, "TEST")
    # Detector cleared its recent buffer after firing; another single repeat
    # shouldn't fire again.
    detector.after_tool("echo", {"x": 1}, {"result": "ok"})
    _patch_publish_event.reset_mock()
    await detector.before_model(_FakeHistory(), 5, "TEST")
    assert _patch_publish_event.call_count == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_action_when_no_tools_called(_patch_publish_event):
    detector = LoopDetector(threshold=3)
    history = _FakeHistory()
    await detector.before_model(history, 1, "TEST")
    assert _patch_publish_event.call_count == 0


@pytest.mark.unit
def test_after_tool_returns_result_unchanged():
    detector = LoopDetector(threshold=3)
    result = {"result": "hello"}
    assert detector.after_tool("t", {}, result) is result
