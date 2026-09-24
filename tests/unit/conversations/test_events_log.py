"""Tests for the events.jsonl writer."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from conversations._events_log import EventsLogWriter, _serialize_event
from agent_core.events import (
    AgentEvent,
    ContentPayload,
    ErrorPayload,
    IterationPayload,
    IterationToolCall,
    ToolCallPayload,
    ToolResultPayload,
    TurnEndPayload,
    UserAttachment,
    UserMessagePayload,
)


@pytest.fixture()
def _conv_dir(tmp_path: Path) -> Path:
    conv_dir = tmp_path / "conversations"
    with patch(
        "conversations._events_log._get_conv_dir",
        return_value=conv_dir / "test-conv",
    ):
        yield conv_dir / "test-conv"


pytestmark = [pytest.mark.unit]


def test_serialize_event_flattens_envelope_and_payload():
    """Serialization lifts envelope fields and payload fields into one flat dict."""
    evt = AgentEvent(
        payload=UserMessagePayload(
            type="user_message",
            content="hello",
            attachments=[UserAttachment(filename="a.png", content_type="image/png", path="/v/a.png")],
        ),
        agent_id="root.agent.1",
        agent_name="COMPUTRON",
        depth=0,
    )

    flat = _serialize_event(evt, "conv-1")

    assert flat["id"].startswith("evt_")
    assert flat["type"] == "user_message"
    assert flat["conversation_id"] == "conv-1"
    assert flat["agent_id"] == "root.agent.1"
    assert flat["agent_name"] == "COMPUTRON"
    assert flat["depth"] == 0
    assert flat["content"] == "hello"
    assert flat["attachments"] == [
        {"filename": "a.png", "content_type": "image/png", "path": "/v/a.png"},
    ]
    # The discriminator must not be duplicated under a "payload" key.
    assert "payload" not in flat


def test_writer_appends_events_in_order(_conv_dir: Path):
    """Each handle_event call appends one JSONL line in publish order."""
    writer = EventsLogWriter("test-conv")
    e1 = AgentEvent(payload=UserMessagePayload(type="user_message", content="hi"))
    e2 = AgentEvent(payload=IterationPayload(
        type="iteration", iteration_index=0,
        content="ok",
        tool_calls=[IterationToolCall(id="c1", name="shell", arguments={"cmd": "ls"})],
    ))
    e3 = AgentEvent(payload=ToolResultPayload(
        type="tool_result", tool_call_id="c1", tool_name="shell", content="files",
    ))

    writer.handle_event(e1)
    writer.handle_event(e2)
    writer.handle_event(e3)

    log = _conv_dir / "events.jsonl"
    lines = log.read_text().splitlines()
    assert len(lines) == 3

    rows = [json.loads(l) for l in lines]
    assert [r["type"] for r in rows] == ["user_message", "iteration", "tool_result"]
    assert rows[0]["id"] == e1.id
    assert rows[1]["tool_calls"][0]["name"] == "shell"
    assert rows[2]["tool_call_id"] == "c1"


def test_writer_creates_conversation_directory(_conv_dir: Path):
    """The writer creates the conv dir lazily on first persisted event."""
    assert not _conv_dir.exists()
    writer = EventsLogWriter("test-conv")
    writer.handle_event(AgentEvent(payload=UserMessagePayload(type="user_message", content="x")))
    assert (_conv_dir / "events.jsonl").exists()


def test_writer_persists_user_visible_errors(_conv_dir: Path):
    """A resumed transcript can show the failure that ended its turn."""
    writer = EventsLogWriter("test-conv")
    writer.handle_event(AgentEvent(payload=ErrorPayload(
        type="error", message="provider unavailable", retryable=True,
    )))

    (row,) = [
        json.loads(line)
        for line in (_conv_dir / "events.jsonl").read_text().splitlines()
    ]
    assert row["type"] == "error"
    assert row["message"] == "provider unavailable"


def test_writer_skips_transient_event_types(_conv_dir: Path):
    """Streaming content deltas, legacy tool_call notifications, and
    turn_end signals are dispatcher-only and never hit disk."""
    writer = EventsLogWriter("test-conv")

    # Persisted: one user_message, one iteration.
    writer.handle_event(AgentEvent(payload=UserMessagePayload(type="user_message", content="hi")))
    # Transient: streaming delta + legacy tool_call notification + turn_end.
    writer.handle_event(AgentEvent(payload=ContentPayload(type="content", content="streaming-bit", delta=True)))
    writer.handle_event(AgentEvent(payload=ToolCallPayload(type="tool_call", name="shell")))
    writer.handle_event(AgentEvent(payload=TurnEndPayload(type="turn_end")))
    # Persisted: iteration carries the rolled-up content + tool calls.
    writer.handle_event(AgentEvent(payload=IterationPayload(
        type="iteration", iteration_index=0, content="full", tool_calls=[],
    )))

    rows = [json.loads(l) for l in (_conv_dir / "events.jsonl").read_text().splitlines()]
    assert [r["type"] for r in rows] == ["user_message", "iteration"]


def test_writer_emits_valid_jsonl_for_every_new_payload(_conv_dir: Path):
    """Every line must round-trip through json.loads with no extra commas/newlines."""
    writer = EventsLogWriter("test-conv")
    writer.handle_event(AgentEvent(payload=UserMessagePayload(type="user_message", content="a")))
    writer.handle_event(AgentEvent(payload=IterationPayload(
        type="iteration", iteration_index=0, content="b", tool_calls=[],
    )))
    writer.handle_event(AgentEvent(payload=ToolResultPayload(
        type="tool_result", tool_call_id="x", tool_name="t", content="r",
    )))
    raw = (_conv_dir / "events.jsonl").read_text()
    for line in raw.splitlines():
        json.loads(line)
