"""Tests for conversation-scoped resource cleanup hooks."""

from unittest.mock import AsyncMock

import pytest

from conversations import _lifecycle as lifecycle


@pytest.fixture(autouse=True)
def _isolated_hooks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep process-global registrations isolated between tests."""
    monkeypatch.setattr(lifecycle, "_hooks", [])


async def test_registered_hook_runs_once_per_exit() -> None:
    """Duplicate registration does not duplicate cleanup."""
    hook = AsyncMock()

    lifecycle.register_conversation_exit_hook(hook)
    lifecycle.register_conversation_exit_hook(hook)
    await lifecycle.run_conversation_exit_hooks("conversation-1")

    hook.assert_awaited_once_with("conversation-1")


async def test_failing_hook_does_not_prevent_other_cleanup() -> None:
    """One subsystem cannot prevent another from releasing its resources."""
    failing = AsyncMock(side_effect=RuntimeError("cleanup failed"))
    succeeding = AsyncMock()
    lifecycle.register_conversation_exit_hook(failing)
    lifecycle.register_conversation_exit_hook(succeeding)

    await lifecycle.run_conversation_exit_hooks("conversation-1")

    failing.assert_awaited_once_with("conversation-1")
    succeeding.assert_awaited_once_with("conversation-1")
