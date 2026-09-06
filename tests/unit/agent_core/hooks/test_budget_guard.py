"""Tests for BudgetGuard hook."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_core.events import UserMessagePayload
from agent_core.hooks import BudgetGuard


class _FakeHistory:
    """Stand-in for ConversationHistory — hooks read but never write to it."""


@pytest.fixture
def _patch_publish_event():
    """Capture publish_event calls so tests can inspect the emitted nudge."""
    with patch("agent_core.hooks._budget_guard.publish_event") as mock:
        yield mock


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_action_within_budget(_patch_publish_event):
    guard = BudgetGuard(5)
    await guard.before_model(_FakeHistory(), 3, "TEST")
    assert _patch_publish_event.call_count == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_triggers_at_limit(_patch_publish_event):
    guard = BudgetGuard(3)
    await guard.before_model(_FakeHistory(), 4, "TEST")
    assert _patch_publish_event.call_count == 1
    payload = _patch_publish_event.call_args[0][0].payload
    assert isinstance(payload, UserMessagePayload)
    assert "budget exhausted" in payload.content.lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_only_triggers_once(_patch_publish_event):
    guard = BudgetGuard(2)
    await guard.before_model(_FakeHistory(), 3, "TEST")
    await guard.before_model(_FakeHistory(), 4, "TEST")
    assert _patch_publish_event.call_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_disabled_when_zero(_patch_publish_event):
    guard = BudgetGuard(0)
    await guard.before_model(_FakeHistory(), 100, "TEST")
    assert _patch_publish_event.call_count == 0
