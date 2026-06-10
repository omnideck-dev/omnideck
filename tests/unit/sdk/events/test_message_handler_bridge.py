"""Tests for message-handler bridging of dispatcher events.

Covers:
- The handler yields only events published via dispatcher (no duplicates)
- Ordering is preserved
- Agent lifecycle events (agent_started, agent_completed) are emitted by agent_span
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agents._agent_profiles import AgentProfile
from server.message_handler import handle_user_message
from sdk.events import (
    AgentCompletedPayload,
    AgentStartedPayload,
    AgentEvent,
    ContentPayload,
    publish_event,
    agent_span,
)
from sdk.turn import StopRequestedError


@pytest.mark.unit
@pytest.mark.asyncio
async def test_message_handler_bridges_events_without_duplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the tool loop to publish events; ensure published events are forwarded
    including lifecycle events from agent_span.
    """

    async def _fake_tool_loop(**_: Any) -> str | None:
        # Root-level event
        publish_event(AgentEvent(payload=ContentPayload(type="content", content="one")))
        await asyncio.sleep(0)

        # Nested agent event: passes through with content intact
        async with agent_span("nested"):
            publish_event(AgentEvent(payload=ContentPayload(type="content", content="secret", thinking="hidden")))
        await asyncio.sleep(0)

        return "done"

    import server.message_handler as mh

    mock_profile = AgentProfile(
        id="computron",
        name="Test",
        provider="ollama",
        model="test-model",
        system_prompt="test",
        skills=[],
    )
    monkeypatch.setattr(mh, "get_agent_profile", lambda _pid: mock_profile)
    monkeypatch.setattr(mh, "run_turn", _fake_tool_loop)
    seen: list[AgentEvent] = []
    async for ev in handle_user_message(
        "hi", data=None, profile_id="computron", conversation_id="test-conv",
    ):
        seen.append(ev)
        if ev.payload.type == "turn_end":
            break

    # Filter to content events and lifecycle events
    content_events = [
        (ev.payload.content, ev.payload.thinking)
        for ev in seen
        if ev.payload.type == "content"
    ]
    lifecycle_events = [
        (ev.payload.type, ev.payload.agent_name)
        for ev in seen
        if isinstance(ev.payload, (AgentStartedPayload, AgentCompletedPayload))
    ]

    # Content events should pass through in order
    assert content_events == [
        ("one", None),
        ("secret", "hidden"),
    ]

    # Lifecycle events: root started, nested started, nested completed, root completed
    agent_names = [name for _, name in lifecycle_events]
    assert "nested" in agent_names

    event_types = [ev.payload.type for ev in seen]
    assert event_types[-1] == "turn_end"
    assert event_types.count("turn_end") == 1
    root_completed_idx = max(
        i for i, ev in enumerate(seen)
        if isinstance(ev.payload, AgentCompletedPayload) and ev.payload.agent_name == "TEST"
    )
    assert root_completed_idx < len(seen) - 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_message_handler_reports_root_agent_stopped_before_turn_end(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stopped root turn should publish stopped lifecycle before final turn_end."""
    async def _stopped_tool_loop(**_: Any) -> str | None:
        publish_event(AgentEvent(payload=ContentPayload(type="content", content="partial")))
        await asyncio.sleep(0)
        raise StopRequestedError()

    import server.message_handler as mh

    mock_profile = AgentProfile(
        id="computron",
        name="Test",
        provider="ollama",
        model="test-model",
        system_prompt="test",
        skills=[],
    )
    monkeypatch.setattr(mh, "get_agent_profile", lambda _pid: mock_profile)
    monkeypatch.setattr(mh, "run_turn", _stopped_tool_loop)

    seen: list[AgentEvent] = []
    async for ev in handle_user_message(
        "hi", data=None, profile_id="computron", conversation_id="test-conv-stop",
    ):
        seen.append(ev)
        if ev.payload.type == "turn_end":
            break

    event_types = [ev.payload.type for ev in seen]
    root_completed = [
        ev for ev in seen
        if isinstance(ev.payload, AgentCompletedPayload) and ev.payload.agent_name == "TEST"
    ]

    assert root_completed
    assert root_completed[-1].payload.status == "stopped"
    assert event_types[-1] == "turn_end"
    assert seen.index(root_completed[-1]) < len(seen) - 1
