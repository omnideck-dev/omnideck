"""Unit tests for the per-agent terminal transcript sidecar."""

from __future__ import annotations

from pathlib import Path

import pytest

from conversations import TerminalWriter, load_terminal
from sdk.events import AgentEvent, ContentPayload, TerminalOutputPayload


@pytest.fixture()
def _conv_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        "conversations._store._get_conversations_dir", lambda: tmp_path,
    )
    return tmp_path


def _term(cmd_id: str, status: str, *, cmd: str = "ls", stdout: str | None = None,
          exit_code: int | None = None, agent_id: str = "root.a.1") -> AgentEvent:
    return AgentEvent(payload=TerminalOutputPayload(
        type="terminal_output", cmd_id=cmd_id, cmd=cmd, status=status,
        stdout=stdout, exit_code=exit_code,
    ), agent_id=agent_id)


def test_completed_replaces_running_entry(_conv_dir: Path) -> None:
    w = TerminalWriter("c1")
    w.handle_event(_term("c-1", "running"))
    w.handle_event(_term("c-1", "completed", stdout="a.txt\n", exit_code=0))

    transcripts = load_terminal("c1")
    (entry,) = transcripts["root.a.1"]
    assert entry["status"] == "completed"
    assert entry["stdout"] == "a.txt\n"
    assert entry["exit_code"] == 0


def test_streaming_chunks_never_touch_disk(_conv_dir: Path) -> None:
    w = TerminalWriter("c1")
    w.handle_event(_term("c-1", "running"))
    w.handle_event(_term("c-1", "streaming", stdout="partial"))

    (entry,) = load_terminal("c1")["root.a.1"]
    assert entry["status"] == "running"
    assert entry["stdout"] is None


def test_caps_entries_per_agent(_conv_dir: Path) -> None:
    w = TerminalWriter("c1")
    for i in range(60):
        w.handle_event(_term(f"c-{i}", "completed", stdout=str(i)))

    lines = load_terminal("c1")["root.a.1"]
    assert len(lines) == 50
    assert lines[0]["cmd_id"] == "c-10"
    assert lines[-1]["cmd_id"] == "c-59"


def test_transcripts_survive_across_writer_instances(_conv_dir: Path) -> None:
    TerminalWriter("c1").handle_event(_term("c-1", "completed", stdout="one"))
    TerminalWriter("c1").handle_event(_term("c-2", "completed", stdout="two"))

    lines = load_terminal("c1")["root.a.1"]
    assert [e["cmd_id"] for e in lines] == ["c-1", "c-2"]


def test_agents_tracked_separately(_conv_dir: Path) -> None:
    w = TerminalWriter("c1")
    w.handle_event(_term("c-1", "completed", agent_id="root.a.1"))
    w.handle_event(_term("c-2", "completed", agent_id="root.a.1.sub.2"))

    transcripts = load_terminal("c1")
    assert set(transcripts) == {"root.a.1", "root.a.1.sub.2"}


def test_non_terminal_events_ignored(_conv_dir: Path) -> None:
    w = TerminalWriter("c1")
    w.handle_event(AgentEvent(payload=ContentPayload(type="content", content="x")))
    assert load_terminal("c1") == {}
    assert not (_conv_dir / "c1" / "terminal.json").exists()
