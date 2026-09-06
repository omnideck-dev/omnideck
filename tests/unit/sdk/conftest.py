"""Test plumbing for the events-first history model.

Production code routes message changes through ``publish_event`` and the
dispatcher; ConversationHistory derives its view from the resulting
event log. Unit tests typically bypass the dispatcher and assert on the
history surface directly.

This conftest bridges the two worlds: it patches
``ConversationHistory.__init__`` to seed an event log from any initial
messages, and patches ``publish_event`` at the execution sites to
forward published events into every ConversationHistory created during
the test. The result is that existing tests using the
``ConversationHistory([...])`` + ``AgentExecutor.execute`` pattern continue to see
the history surface populated as they always did.
"""

from __future__ import annotations

from typing import Any

import pytest

_TEST_CONV_ID = "test"
_TEST_AGENT_ID = "test-agent"
_TEST_AGENT_NAME = "test-agent"


def _event_envelope(evt_id: str, evt_type: str, idx: int) -> dict[str, Any]:
    return {
        "id": evt_id,
        "type": evt_type,
        "timestamp": f"2026-01-01T00:00:{idx:02d}",
        "conversation_id": _TEST_CONV_ID,
        "agent_id": _TEST_AGENT_ID,
        "agent_name": _TEST_AGENT_NAME,
        "depth": 0,
    }


def _seed_events_from_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate a list of message dicts into the flat event shape.

    If the messages list has no user message, a synthetic anchor user
    message is injected so derived-view tests have an anchor without
    forcing every test to fabricate one explicitly.
    """
    events: list[dict[str, Any]] = [{
        **_event_envelope("evt_test_started", "agent_started", 0),
        "parent_agent_id": None,
    }]
    if not any(m.get("role") == "user" for m in messages):
        events.append({
            **_event_envelope("evt_test_anchor_user", "user_message", 0),
            "content": "(test anchor)",
            "attachments": [],
        })
    for i, m in enumerate(messages, start=1):
        role = m.get("role")
        if role == "system":
            continue
        if role == "user":
            events.append({
                **_event_envelope(f"evt_test_u{i}", "user_message", i),
                "content": m.get("content", ""),
                "attachments": [],
            })
        elif role == "assistant":
            tcs = []
            for tc in (m.get("tool_calls") or []):
                fn = tc.get("function") or {}
                tcs.append({
                    "id": tc.get("id"),
                    "name": fn.get("name"),
                    "arguments": fn.get("arguments"),
                })
            events.append({
                **_event_envelope(f"evt_test_i{i}", "iteration", i),
                "iteration_index": i - 1,
                "content": m.get("content"),
                "thinking": m.get("thinking"),
                "tool_calls": tcs,
            })
        elif role == "tool":
            events.append({
                **_event_envelope(f"evt_test_t{i}", "tool_result", i),
                "tool_call_id": m.get("tool_call_id"),
                "tool_name": m.get("tool_name"),
                "content": m.get("content", ""),
            })
    return events


@pytest.fixture(autouse=True)
def _events_first_test_bridge(monkeypatch):
    """Make ConversationHistory + publish_event tests-friendly.

    On entry:
    - ``ConversationHistory.__init__`` is patched so each instance gets
      ``conversation_id`` / ``agent_id`` defaults and a seeded event log
      reflecting any initial messages.
    - ``publish_event`` in the tool-loop and tool-call modules is
      patched to forward enriched events into every tracked history.

    The original implementations are restored automatically on teardown
    via monkeypatch.
    """
    from sdk.context._history import ConversationHistory

    original_init = ConversationHistory.__init__
    tracked: list[ConversationHistory] = []

    def patched_init(self, messages: list[dict[str, Any]] | None = None,
                      *,
                      conversation_id: str | None = None,
                      agent_id: str | None = None) -> None:
        # Only inject test defaults when the caller didn't specify a
        # conversation_id. Tests that pass their own conversation_id are
        # exercising the new conversation-owned publish path and should
        # not have their agent_id overridden.
        explicit = conversation_id is not None
        if not explicit:
            conversation_id = _TEST_CONV_ID
            agent_id = agent_id or _TEST_AGENT_ID
        # Production takes only the system message; the rest of the list is
        # seeded as events below to reproduce the old all-in-one ergonomics.
        system_message = next(
            (m.get("content", "") for m in (messages or []) if m.get("role") == "system"),
            None,
        )
        original_init(
            self, system_message,
            conversation_id=conversation_id, agent_id=agent_id,
        )
        if messages and not explicit:
            self.seed_events(_seed_events_from_messages(messages))
        if not explicit:
            tracked.append(self)

    monkeypatch.setattr(ConversationHistory, "__init__", patched_init)

    def make_forwarder(real_publish):
        def fake_publish(event):
            real_publish(event)
            enriched = event.model_copy(update={
                "agent_id": _TEST_AGENT_ID, "agent_name": _TEST_AGENT_NAME,
            })
            for h in tracked:
                h.handle_event(enriched)
        return fake_publish

    # Forward events from every site that publishes during the turn so
    # tests see history populated from the dispatched stream. The
    # ``sdk.events`` package re-export covers lazy-import sites
    # (notably ``sdk.tools._helpers``).
    import sdk.events as _events
    import sdk.turn._execution as _execution
    import sdk.context._strategy as _strategy

    targets: list[tuple[Any, str]] = [
        (_events, "publish_event"),
        (_execution, "publish_event"),
        (_strategy, "publish_event"),
    ]
    # Hook modules import publish_event eagerly when present.
    for modname in (
        "sdk.hooks._nudge_hook",
        "sdk.hooks._loop_detector",
        "sdk.hooks._stop_hook",
        "sdk.hooks._budget_guard",
    ):
        try:
            mod = __import__(modname, fromlist=["publish_event"])
        except ImportError:
            continue
        if hasattr(mod, "publish_event"):
            targets.append((mod, "publish_event"))

    for mod, attr in targets:
        monkeypatch.setattr(mod, attr, make_forwarder(getattr(mod, attr)))
    yield
