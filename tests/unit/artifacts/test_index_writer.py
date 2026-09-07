"""Unit tests for the artifacts index writer (the event observer)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from artifacts import ArtifactsIndexWriter, list_artifacts
from agent_core.events._models import (
    AgentEvent,
    FileOutputPayload,
    TerminalOutputPayload,
)


def _file_event(path: str, *, filename: str = "out.md") -> AgentEvent:
    return AgentEvent(
        payload=FileOutputPayload(
            type="file_output",
            filename=filename,
            content_type="text/markdown",
            path=path,
        ),
        agent_name="Claude",
        agent_id="root.claude.0",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_records_file_output_event(make_file) -> None:
    path = make_file("out.md")
    ArtifactsIndexWriter("c1").handle_event(_file_event(path))

    entries = list_artifacts()
    assert len(entries) == 1
    e = entries[0]
    assert e.conversation_id == "c1"
    assert e.path == path
    assert e.filename == "out.md"
    assert e.agent_name == "Claude"
    assert e.created_at == "2026-01-01T00:00:00+00:00"


def test_ignores_non_file_output_events(vc_home: Path) -> None:
    event = AgentEvent(
        payload=TerminalOutputPayload(type="terminal_output", cmd_id="x", cmd="ls"),
    )
    ArtifactsIndexWriter("c1").handle_event(event)
    assert list_artifacts() == []


def test_ignores_file_output_without_path(vc_home: Path) -> None:
    event = AgentEvent(
        payload=FileOutputPayload(
            type="file_output", filename="legacy.bin",
            content_type="application/octet-stream", content="QUJD",
        ),
    )
    ArtifactsIndexWriter("c1").handle_event(event)
    assert list_artifacts() == []
