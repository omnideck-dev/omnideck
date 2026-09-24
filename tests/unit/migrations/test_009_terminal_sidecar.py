"""Tests for migration 009 — move terminal events out of events.jsonl."""

from __future__ import annotations

import json
from pathlib import Path

from migrations._009_terminal_sidecar import migrate


def _write_log(conv_dir: Path, events: list[dict]) -> None:
    conv_dir.mkdir(parents=True, exist_ok=True)
    (conv_dir / "events.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8",
    )


def _read_log(conv_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (conv_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _term(cmd_id: str, status: str, *, stdout: str | None = None,
          exit_code: int | None = None, agent_id: str = "root.a.1") -> dict:
    return {
        "id": f"evt_{cmd_id}_{status}", "type": "terminal_output",
        "timestamp": "2026-01-01T00:00:01+00:00", "conversation_id": "c1",
        "agent_id": agent_id, "cmd_id": cmd_id, "cmd": "make build",
        "status": status, "stdout": stdout, "stderr": None, "exit_code": exit_code,
    }


def test_collapses_terminal_events_into_sidecar(tmp_path: Path) -> None:
    conv = tmp_path / "conversations" / "c1"
    _write_log(conv, [
        {"id": "e1", "type": "user_message", "content": "build it", "agent_id": "root.a.1"},
        _term("c-1", "running"),
        _term("c-1", "streaming", stdout="compiling...\n"),
        _term("c-1", "streaming", stdout="linking...\n"),
        _term("c-1", "completed", stdout="compiling...\nlinking...\nok\n", exit_code=0),
        {"id": "e2", "type": "iteration", "content": "built", "agent_id": "root.a.1"},
    ])

    migrate(tmp_path)

    assert [e["type"] for e in _read_log(conv)] == ["user_message", "iteration"]

    transcripts = json.loads((conv / "terminal.json").read_text(encoding="utf-8"))
    (entry,) = transcripts["root.a.1"]
    assert entry["status"] == "completed"
    assert entry["stdout"] == "compiling...\nlinking...\nok\n"
    assert entry["exit_code"] == 0

    backup = tmp_path / ".backups" / "009_terminal_sidecar" / "conversations" / "c1" / "events.jsonl"
    assert backup.exists()


def test_command_without_completed_keeps_streamed_output(tmp_path: Path) -> None:
    """A hard-killed command never completed; its streamed output survives."""
    conv = tmp_path / "conversations" / "c1"
    _write_log(conv, [
        _term("c-1", "running"),
        _term("c-1", "streaming", stdout="partial out"),
    ])

    migrate(tmp_path)

    (entry,) = json.loads((conv / "terminal.json").read_text(encoding="utf-8"))["root.a.1"]
    assert entry["status"] == "streaming"
    assert entry["stdout"] == "partial out"


def test_noop_for_logs_without_terminal_events(tmp_path: Path) -> None:
    conv = tmp_path / "conversations" / "clean"
    _write_log(conv, [
        {"id": "e1", "type": "user_message", "content": "hi", "agent_id": "root.a.1"},
    ])
    before = (conv / "events.jsonl").read_text(encoding="utf-8")

    migrate(tmp_path)

    assert (conv / "events.jsonl").read_text(encoding="utf-8") == before
    assert not (conv / "terminal.json").exists()
    assert not (tmp_path / ".backups").exists()


def test_existing_sidecar_agents_win_over_log_derived(tmp_path: Path) -> None:
    conv = tmp_path / "conversations" / "c1"
    _write_log(conv, [_term("c-old", "completed", stdout="stale")])
    (conv / "terminal.json").write_text(json.dumps({
        "root.a.1": [{"cmd_id": "c-live", "cmd": "ls", "status": "completed",
                      "stdout": "fresh", "stderr": None, "exit_code": 0,
                      "agent_id": "root.a.1", "timestamp": "2026-01-02T00:00:00+00:00"}],
    }), encoding="utf-8")

    migrate(tmp_path)

    lines = json.loads((conv / "terminal.json").read_text(encoding="utf-8"))["root.a.1"]
    assert [e["cmd_id"] for e in lines] == ["c-live"]
    assert _read_log(conv) == []
