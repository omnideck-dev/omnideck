"""Cancellation remains bounded even when the renderer stops responding."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from playwright.async_api import CDPSession, Frame

from browser.core import evaluation


async def test_cancelled_evaluation_bounds_cleanup_and_detaches(monkeypatch):
    frame = MagicMock(spec=Frame)
    session = MagicMock(spec=CDPSession)

    async def unresponsive(*_args, **_kwargs):
        await asyncio.Event().wait()

    session.send = AsyncMock(side_effect=unresponsive)
    session.detach = AsyncMock(side_effect=unresponsive)
    monkeypatch.setattr(evaluation, "_attach", AsyncMock(return_value=(session, frame)))
    monkeypatch.setattr(
        evaluation,
        "_main_context",
        AsyncMock(return_value=evaluation._ExecutionContext(1, "document-1", "frame-1")),
    )
    monkeypatch.setattr(evaluation, "_CLEANUP_TIMEOUT_SECONDS", 0.02)

    started = asyncio.get_running_loop().time()
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(evaluation.evaluate_frame(frame, "while (true) {}"), timeout=0.02)

    assert asyncio.get_running_loop().time() - started < 1
    assert [call.args[0] for call in session.send.await_args_list] == [
        "Runtime.evaluate",
        "Runtime.releaseObjectGroup",
    ]
    session.detach.assert_awaited_once()
