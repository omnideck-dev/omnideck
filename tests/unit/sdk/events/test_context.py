"""Unit tests for context-bound event publishing utilities.

These tests validate that:
- publish_event is a no-op when no event sink is bound
- publish_event forwards the enriched event to the active event sink
- agent_span forms a hierarchy of context ids
"""

from __future__ import annotations

import pytest

from sdk.events import (
    AgentEvent,
    ContentPayload,
    UserMessagePayload,
    agent_span,
    publish_event,
    reset_current_event_sink,
    set_current_event_sink,
)


class _RecordingSink:
    """Minimal EventSink stub: records every event handed to add_event.

    Keeps the events-layer test within the events layer — it depends only on
    the EventSink protocol, not on a concrete conversation's event-to-message
    derivation.
    """

    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    def add_event(self, event: AgentEvent) -> None:
        self.events.append(event)


@pytest.mark.unit
def test_publish_event_noop_without_event_sink() -> None:
    """Calling publish_event without a bound sink should not raise."""
    # No sink bound: should be a silent no-op.
    publish_event(AgentEvent(payload=ContentPayload(type="content", content="hi")))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_publish_event_forwards_enriched_event_to_sink() -> None:
    """publish_event forwards the event to the bound sink synchronously,
    enriched with the active span's agent attribution."""
    sink = _RecordingSink()
    token = set_current_event_sink(sink)
    try:
        # agent_span pushes its id on the context stack so publish_event can
        # tag the event with the active agent's id / name / depth.
        async with agent_span("TEST"):
            publish_event(AgentEvent(
                payload=UserMessagePayload(type="user_message", content="hello"),
            ))
    finally:
        reset_current_event_sink(token)

    # The span itself emits agent_started / agent_completed; pick out the
    # user_message we published.
    user_events = [
        e for e in sink.events
        if isinstance(e.payload, UserMessagePayload)
    ]
    assert len(user_events) == 1
    event = user_events[0]
    assert event.payload.content == "hello"
    assert event.agent_name == "TEST"
    assert event.depth == 0
    assert event.agent_id is not None and event.agent_id.startswith("root")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_child_context_ids_form_hierarchy() -> None:
    """Child context ids should extend their parent ids deterministically."""
    async with agent_span("root") as root_id:
        async with agent_span("nested") as child_id:
            assert child_id.startswith(root_id)
            async with agent_span("deep") as grandchild_id:
                assert grandchild_id.startswith(child_id)
