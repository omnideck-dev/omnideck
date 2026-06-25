"""Tests for ConversationHistory — events-first edition."""

import pytest

from sdk.context import ConversationHistory


@pytest.fixture(autouse=True)
def _events_first_test_bridge():
    """Override the parent SDK conftest's auto-init patching.

    These tests exercise the raw ConversationHistory API and need
    full control over construction arguments and the event log.
    """
    yield


def _user(content: str, evt_id: str = "evt_u") -> dict:
    return {
        "id": evt_id,
        "type": "user_message",
        "timestamp": "2026-01-01T00:00:00",
        "conversation_id": "test",
        "agent_id": "test-agent",
        "depth": 0,
        "content": content,
        "attachments": [],
    }


def _iter(content: str, idx: int = 0, evt_id: str = "evt_i") -> dict:
    return {
        "id": evt_id,
        "type": "iteration",
        "timestamp": f"2026-01-01T00:00:{10 + idx:02d}",
        "conversation_id": "test",
        "agent_id": "test-agent",
        "depth": 0,
        "iteration_index": idx,
        "content": content,
        "thinking": None,
        "tool_calls": [],
    }


def _agent_started(agent_id: str = "test-agent", name: str = "test-agent", parent: str | None = None) -> dict:
    return {
        "id": f"evt_started_{agent_id}",
        "type": "agent_started",
        "timestamp": "2026-01-01T00:00:00",
        "conversation_id": "test",
        "agent_id": agent_id,
        "agent_name": name,
        "parent_agent_id": parent,
        "depth": 0 if parent is None else 1,
    }


@pytest.mark.unit
class TestEmptyConstruction:
    """Empty / no-events behavior."""

    def test_empty_init(self):
        h = ConversationHistory()
        assert h.messages == []
        assert h.system_message is None
        assert h.non_system_messages == []
        assert h.recorded_events == []

    def test_repr_reflects_message_count(self):
        h = ConversationHistory(conversation_id="test")
        h.seed_events([_agent_started(), _user("hi"), _iter("hello")])
        assert "len=2" in repr(h)


@pytest.mark.unit
class TestSystemMessage:
    """System message is held separately from the event log."""

    def test_system_message_from_constructor(self):
        h = ConversationHistory(system_message="sys")
        assert h.system_message == {"role": "system", "content": "sys"}

    def test_set_system_message_replaces(self):
        h = ConversationHistory(system_message="old")
        h.set_system_message("new")
        assert h.system_message == {"role": "system", "content": "new"}

    def test_set_system_message_when_absent(self):
        h = ConversationHistory()
        h.set_system_message("sys")
        assert h.system_message == {"role": "system", "content": "sys"}

    def test_system_message_returns_copy(self):
        h = ConversationHistory(system_message="sys")
        s = h.system_message
        s["content"] = "tampered"
        assert h.system_message["content"] == "sys"


@pytest.mark.unit
class TestDerivedMessages:
    """messages / non_system_messages derive from the event log."""

    def test_derived_returns_empty_without_conversation_id(self):
        """No conversation_id = nothing to derive against; safe empty list."""
        h = ConversationHistory(system_message="sys")
        h.seed_events([_agent_started(), _user("hi"), _iter("hello")])
        # No conversation_id, so derived is empty even though events were seeded.
        assert h.non_system_messages == []
        assert h.messages == [{"role": "system", "content": "sys"}]

    def test_derived_view_after_seeding(self):
        h = ConversationHistory(conversation_id="test")
        h.seed_events([_agent_started(), _user("hi"), _iter("hello")])
        assert h.non_system_messages == [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello", "agent_name": "test-agent"},
        ]

    def test_messages_prepends_system_to_derived(self):
        h = ConversationHistory(system_message="sys", conversation_id="test")
        h.seed_events([_agent_started(), _user("hi"), _iter("hello")])
        assert h.messages[0] == {"role": "system", "content": "sys"}
        assert len(h.messages) == 3


@pytest.mark.unit
class TestSeedAndHandle:
    """seed_events + handle_event keep the in-memory log in sync."""

    def test_seed_events_replaces_existing_log(self):
        h = ConversationHistory(conversation_id="test")
        h.seed_events([_agent_started(), _user("first")])
        h.seed_events([_agent_started(), _user("second")])
        assert h.non_system_messages == [{"role": "user", "content": "second"}]

    def test_handle_event_appends_to_log(self):
        from sdk.events import AgentEvent, UserMessagePayload
        h = ConversationHistory(conversation_id="test", agent_id="test-agent")
        h.seed_events([_agent_started()])
        h.handle_event(AgentEvent(
            payload=UserMessagePayload(type="user_message", content="live"),
            agent_id="test-agent",
        ))
        assert h.non_system_messages == [{"role": "user", "content": "live"}]

    def test_handle_event_filters_transient_types(self):
        """Streaming content deltas + legacy tool_call don't enter the log."""
        from sdk.events import AgentEvent, ContentPayload, ToolCallPayload
        h = ConversationHistory(conversation_id="test", agent_id="test-agent")
        h.handle_event(AgentEvent(payload=ContentPayload(type="content", content="stream")))
        h.handle_event(AgentEvent(payload=ToolCallPayload(type="tool_call", name="t")))
        assert h.recorded_events == []

    def test_handle_event_no_op_without_conversation_id(self):
        from sdk.events import AgentEvent, UserMessagePayload
        h = ConversationHistory()
        h.handle_event(AgentEvent(
            payload=UserMessagePayload(type="user_message", content="x"),
        ))
        assert h.recorded_events == []


# ── conversation as canonical write + observer fan-out ────────────────


import asyncio

import pytest

from sdk.events import (
    AgentEvent,
    UserMessagePayload,
    agent_span,
    publish_event,
    reset_current_conversation,
    set_current_conversation,
)


def _seed_root_agent(h: ConversationHistory, agent_id: str = "root.computron.1") -> str:
    """Seed a root agent_started so user_message events are scoped to a
    root agent and build_llm_view will include them."""
    from sdk.events import AgentStartedPayload
    h.add_event(AgentEvent(
        payload=AgentStartedPayload(
            type="agent_started", agent_id=agent_id,
            agent_name="COMPUTRON", parent_agent_id=None,
        ),
        agent_id=agent_id, agent_name="COMPUTRON", depth=0,
    ))
    return agent_id


@pytest.mark.unit
def test_add_event_is_synchronous_for_derived_view():
    """The whole point of conversation-owns-the-log: derived view reflects
    the new event before add_event returns. Caller does not need to await
    or sleep(0) to see its own publish."""
    h = ConversationHistory(conversation_id="c1")
    agent_id = _seed_root_agent(h)
    evt = AgentEvent(
        payload=UserMessagePayload(type="user_message", content="hello"),
        agent_id=agent_id, agent_name="COMPUTRON", depth=0,
    )
    h.add_event(evt)
    # No await between add_event and read — the message must be present.
    msgs = h.messages
    assert any(m.get("role") == "user" and m.get("content") == "hello" for m in msgs)


@pytest.mark.unit
def test_add_event_notifies_sync_observer_inline():
    """Sync observers receive the event before add_event returns — no
    deferral through call_soon."""
    h = ConversationHistory(conversation_id="c1")
    received: list[AgentEvent] = []
    h.subscribe(received.append)
    h.add_event(AgentEvent(payload=UserMessagePayload(
        type="user_message", content="x",
    )))
    # No yield, no sleep — the observer ran inline.
    assert len(received) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_publish_event_writes_to_conversation_synchronously():
    """Regression: when a conversation is bound, publish_event writes
    to it BEFORE returning. The first model call after publishing a
    user_message must see that user_message in history.messages — the
    previous design deferred the write via dispatcher call_soon, so
    the model would only see the system message on the first iteration
    and hallucinate without ever reading the user prompt.
    """
    h = ConversationHistory(conversation_id="c1")
    token = set_current_conversation(h)
    try:
        # agent_span emits agent_started and pushes its id on the context
        # stack — same path real code takes. The user_message lands tagged
        # with the span's id, making it a root agent's event.
        async with agent_span("COMPUTRON"):
            publish_event(AgentEvent(payload=UserMessagePayload(
                type="user_message", content="run echo X in bash",
            )))
            # Critical: no await/sleep between publish_event and read.
            # Read BEFORE the span exits so we exercise the in-turn
            # invariant (the model would read history at this point).
            msgs = h.messages
    finally:
        reset_current_conversation(token)
    assert any(
        m.get("role") == "user" and "echo X in bash" in (m.get("content") or "")
        for m in msgs
    ), "user_message must be visible to the model on the next read"


@pytest.mark.unit
def test_publish_event_no_op_without_conversation(caplog):
    """publish_event is a no-op when no conversation is bound — the
    dispatcher fallback was dropped along with the rest of the legacy
    pub/sub plumbing."""
    # Should not raise.
    publish_event(AgentEvent(payload=UserMessagePayload(
        type="user_message", content="orphan",
    )))


@pytest.mark.unit
def test_add_event_filters_non_derived_types_from_in_memory_log():
    """terminal_output / file_output / browser_screenshot are observer-only
    — persisted to disk via observers, but never affect the LLM view.
    The in-memory _events list (which feeds derived_messages) excludes them."""
    from sdk.events import FileOutputPayload
    h = ConversationHistory(conversation_id="c1")
    h.add_event(AgentEvent(payload=FileOutputPayload(
        type="file_output", filename="x.txt", content_type="text/plain", path="/tmp/x.txt",
    )))
    assert h.recorded_events == []


# ── observer fan-out edge cases ───────────────────────────────────────


@pytest.mark.unit
def test_subscribe_is_idempotent():
    """Subscribing the same handler twice is a no-op — the handler should
    still receive each event exactly once, not duplicated."""
    h = ConversationHistory(conversation_id="c1")
    received: list[AgentEvent] = []
    h.subscribe(received.append)
    h.subscribe(received.append)
    h.add_event(AgentEvent(payload=UserMessagePayload(
        type="user_message", content="hi",
    )))
    assert len(received) == 1


@pytest.mark.unit
def test_unsubscribe_unknown_handler_is_safe():
    """Unsubscribing a handler that was never subscribed must not raise."""
    h = ConversationHistory(conversation_id="c1")
    def _noop(_evt: AgentEvent) -> None:
        pass
    # Should not raise.
    h.unsubscribe(_noop)


@pytest.mark.unit
def test_unsubscribe_during_publish_does_not_break_fanout():
    """An observer that removes itself while being notified must not
    cause add_event to crash or skip subsequent observers."""
    h = ConversationHistory(conversation_id="c1")
    other_received: list[AgentEvent] = []

    def _self_removing(evt: AgentEvent) -> None:
        h.unsubscribe(_self_removing)

    h.subscribe(_self_removing)
    h.subscribe(other_received.append)
    h.add_event(AgentEvent(payload=UserMessagePayload(
        type="user_message", content="x",
    )))
    # _self_removing ran and unsubscribed; other observer still got the event.
    assert len(other_received) == 1
    # Next publish: only the other observer fires.
    h.add_event(AgentEvent(payload=UserMessagePayload(
        type="user_message", content="y",
    )))
    assert len(other_received) == 2


@pytest.mark.unit
def test_add_event_notifies_observers_for_non_derived_types():
    """file_output / terminal_output / browser_screenshot are skipped
    from the in-memory LLM view but observers still see them — disk
    persistence and SSE streaming need the full event stream."""
    from sdk.events import FileOutputPayload
    h = ConversationHistory(conversation_id="c1")
    received: list[AgentEvent] = []
    h.subscribe(received.append)
    h.add_event(AgentEvent(payload=FileOutputPayload(
        type="file_output", filename="x.txt",
        content_type="text/plain", path="/tmp/x.txt",
    )))
    assert h.recorded_events == []  # not in LLM view
    assert len(received) == 1       # but observers got it
    assert received[0].payload.type == "file_output"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_drain_observers_waits_for_in_flight_async_handlers():
    """drain_observers must await any in-flight async observer tasks
    before returning so the caller can rely on disk writes etc. having
    landed at the drain point."""
    h = ConversationHistory(conversation_id="c1")
    completion_order: list[str] = []

    async def _slow(evt: AgentEvent) -> None:
        await asyncio.sleep(0.01)
        completion_order.append("observer")

    h.subscribe(_slow)
    h.add_event(AgentEvent(payload=UserMessagePayload(
        type="user_message", content="x",
    )))
    # add_event scheduled the async observer but did not await it.
    assert completion_order == []
    await h.drain_observers()
    completion_order.append("drained")
    # The observer ran before drain_observers returned.
    assert completion_order == ["observer", "drained"]


# ── sub-agent shares parent conversation ──────────────────────────────


@pytest.mark.unit
def test_sub_history_subscribed_to_parent_receives_events():
    """The pattern spawn_agent uses: a sub-agent's ConversationHistory is
    subscribed to the parent's conversation as an observer. Events
    published anywhere in the conversation must reach both the parent's
    in-memory log AND the sub-agent's, so each side can build its own
    LLM view via the agent_id filter."""
    parent = ConversationHistory(conversation_id="c1")
    sub = ConversationHistory(conversation_id="c1", agent_id="sub-id")
    parent.subscribe(sub.handle_event)
    # An event published into the parent (via the canonical add_event)
    # must show up in the sub's _events too.
    parent.add_event(AgentEvent(
        payload=UserMessagePayload(type="user_message", content="hi"),
        agent_id="sub-id", agent_name="SUB", depth=1,
    ))
    assert any(
        e["type"] == "user_message" and e.get("agent_id") == "sub-id"
        for e in parent.recorded_events
    )
    assert any(
        e["type"] == "user_message" and e.get("agent_id") == "sub-id"
        for e in sub.recorded_events
    )


@pytest.mark.unit
def test_sub_history_subscribe_unsubscribe_lifecycle():
    """spawn_agent subscribes the sub-history on enter and unsubscribes
    on exit. Simulate that lifecycle in isolation: subscribe, publish
    one event, unsubscribe, publish another — sub records the first but
    not the second, and the parent's observer list goes back to empty."""
    parent = ConversationHistory(conversation_id="c1")
    sub = ConversationHistory(conversation_id="c1", agent_id="sub-id")
    parent.subscribe(sub.handle_event)
    parent.add_event(AgentEvent(
        payload=UserMessagePayload(type="user_message", content="first"),
        agent_id="sub-id", agent_name="SUB", depth=1,
    ))
    parent.unsubscribe(sub.handle_event)
    parent.add_event(AgentEvent(
        payload=UserMessagePayload(type="user_message", content="post"),
        agent_id="parent-id", agent_name="PARENT", depth=0,
    ))
    sub_contents = [e["content"] for e in sub.recorded_events
                    if e["type"] == "user_message"]
    assert sub_contents == ["first"]
    assert parent._observers == []
