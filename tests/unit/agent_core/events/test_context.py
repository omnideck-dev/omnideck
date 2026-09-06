"""Unit tests for context-bound event publishing utilities.

These tests validate that:
- publish_event is a no-op when no conversation is bound
- _current_conversation can be set/reset via ContextVar directly
- publish_event writes to the active conversation
- agent_span forms a hierarchy of context ids
"""

from __future__ import annotations

import pytest

from agent_core.context import ConversationHistory
from agent_core.events import (
    AgentEvent,
    AgentStartedPayload,
    ContentPayload,
    UserMessagePayload,
    agent_span,
    publish_event,
    reset_current_conversation,
    set_current_conversation,
)


def _seed_root_agent(h: ConversationHistory, agent_id: str = "root.test.1") -> str:
    h.add_event(AgentEvent(
        payload=AgentStartedPayload(
            type="agent_started", agent_id=agent_id,
            agent_name="TEST", parent_agent_id=None,
        ),
        agent_id=agent_id, agent_name="TEST", depth=0,
    ))
    return agent_id


@pytest.mark.unit
def test_publish_event_noop_without_conversation() -> None:
    """Calling publish_event without a conversation should not raise."""
    # No conversation bound: should be a silent no-op.
    publish_event(AgentEvent(payload=ContentPayload(type="content", content="hi")))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_publish_event_writes_to_active_conversation() -> None:
    """publish_event appends the event to the bound conversation's log
    synchronously — no await/sleep needed before reading messages."""
    h = ConversationHistory(conversation_id="c1")
    token = set_current_conversation(h)
    try:
        # agent_span emits agent_started and pushes its id on the context
        # stack so publish_event can tag the user_message with a valid
        # root agent_id; otherwise the derived view filters it out.
        async with agent_span("TEST"):
            publish_event(AgentEvent(
                payload=UserMessagePayload(type="user_message", content="hello"),
            ))
            # No await/sleep between publish and read.
            msgs = list(h.messages)
    finally:
        reset_current_conversation(token)
    assert any(
        m.get("role") == "user" and m.get("content") == "hello"
        for m in msgs
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_child_context_ids_form_hierarchy() -> None:
    """Child context ids should extend their parent ids deterministically."""
    async with agent_span("root") as root_id:
        async with agent_span("nested") as child_id:
            assert child_id.startswith(root_id)
            async with agent_span("deep") as grandchild_id:
                assert grandchild_id.startswith(child_id)
