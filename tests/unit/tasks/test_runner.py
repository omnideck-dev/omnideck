"""Tests for the background task runner lifecycle."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tasks._runner import TaskRunner


@pytest.mark.unit
async def test_stop_cancels_tasks_remaining_after_shutdown_timeout() -> None:
    runner = TaskRunner(
        store=MagicMock(),
        executor=MagicMock(),
        config=SimpleNamespace(shutdown_timeout=0),
    )
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def _stuck_execution() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    execution = asyncio.create_task(_stuck_execution())
    runner._running["result-1"] = execution
    await started.wait()

    await runner.stop()

    assert execution.cancelled()
    assert cancelled.is_set()
