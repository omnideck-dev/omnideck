"""Tests for migration 010: backfill the artifacts index from event logs."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from artifacts import list_artifacts
from migrations._010_backfill_artifacts_index import migrate

pytestmark = pytest.mark.unit


@pytest.fixture()
def env(tmp_path: Path, monkeypatch) -> SimpleNamespace:
    """Point the artifacts index + VC home at temp dirs; state_dir is tmp_path."""
    vc_home = tmp_path / "vc"
    vc_home.mkdir()
    index_path = tmp_path / "artifacts" / "index.json"
    monkeypatch.setattr("artifacts._store._index_path", lambda: index_path)
    monkeypatch.setattr("artifacts._store._vc_home", lambda: vc_home.resolve())
    return SimpleNamespace(state_dir=tmp_path, vc_home=vc_home)


def _make_file(vc_home: Path, name: str) -> str:
    p = vc_home / name
    p.write_text("data", encoding="utf-8")
    return str(p)


def _file_event(path: str, *, ts: str, filename: str | None = None, agent: str = "Claude") -> dict:
    return {
        "id": "evt_x", "type": "file_output", "timestamp": ts,
        "conversation_id": "ignored", "agent_id": "root.x.0", "agent_name": agent,
        "depth": 0, "filename": filename or Path(path).name,
        "content_type": "text/markdown", "path": path,
    }


def _write_events(state_dir: Path, conv_id: str, events: list[dict]) -> None:
    d = state_dir / "conversations" / conv_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "events.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8",
    )


def test_indexes_existing_files(env) -> None:
    a = _make_file(env.vc_home, "a.md")
    b = _make_file(env.vc_home, "b.md")
    _write_events(env.state_dir, "c1", [
        _file_event(a, ts="2026-01-01T00:00:00"),
        _file_event(b, ts="2026-01-01T01:00:00"),
    ])
    migrate(env.state_dir)
    assert {e.filename for e in list_artifacts()} == {"a.md", "b.md"}
    assert {e.conversation_id for e in list_artifacts()} == {"c1"}


def test_skips_missing_files(env) -> None:
    here = _make_file(env.vc_home, "here.md")
    gone = str(env.vc_home / "gone.md")  # never created on disk
    _write_events(env.state_dir, "c1", [
        _file_event(here, ts="2026-01-01T00:00:00"),
        _file_event(gone, ts="2026-01-01T01:00:00"),
    ])
    migrate(env.state_dir)
    assert [e.filename for e in list_artifacts()] == ["here.md"]


def test_ignores_non_file_output_events(env) -> None:
    a = _make_file(env.vc_home, "a.md")
    _write_events(env.state_dir, "c1", [
        {"id": "e1", "type": "agent_started", "timestamp": "2026-01-01T00:00:00",
         "conversation_id": "c1", "agent_id": "root.x.0", "agent_name": "Claude"},
        _file_event(a, ts="2026-01-01T01:00:00"),
    ])
    migrate(env.state_dir)
    assert [e.filename for e in list_artifacts()] == ["a.md"]


def test_skips_file_output_without_path(env) -> None:
    event = _file_event("ignored", ts="2026-01-01T00:00:00")
    del event["path"]
    _write_events(env.state_dir, "c1", [event])
    migrate(env.state_dir)
    assert list_artifacts() == []


def test_dedupes_repeated_path_created_and_updated(env) -> None:
    a = _make_file(env.vc_home, "a.md")
    _write_events(env.state_dir, "c1", [
        _file_event(a, ts="2026-01-01T00:00:00"),
        _file_event(a, ts="2026-02-01T00:00:00"),
    ])
    migrate(env.state_dir)
    entries = list_artifacts()
    assert len(entries) == 1
    assert entries[0].created_at == "2026-01-01T00:00:00"
    assert entries[0].updated_at == "2026-02-01T00:00:00"


def test_multiple_conversations(env) -> None:
    a = _make_file(env.vc_home, "a.md")
    b = _make_file(env.vc_home, "b.md")
    _write_events(env.state_dir, "c1", [_file_event(a, ts="2026-01-01T00:00:00")])
    _write_events(env.state_dir, "c2", [_file_event(b, ts="2026-01-01T00:00:00")])
    migrate(env.state_dir)
    assert {(e.conversation_id, e.filename) for e in list_artifacts()} == {
        ("c1", "a.md"), ("c2", "b.md"),
    }


def test_idempotent_on_rerun(env) -> None:
    a = _make_file(env.vc_home, "a.md")
    _write_events(env.state_dir, "c1", [
        _file_event(a, ts="2026-01-01T00:00:00"),
        _file_event(a, ts="2026-02-01T00:00:00"),
    ])
    migrate(env.state_dir)
    migrate(env.state_dir)
    entries = list_artifacts()
    assert len(entries) == 1
    assert entries[0].created_at == "2026-01-01T00:00:00"
    assert entries[0].updated_at == "2026-02-01T00:00:00"


def test_no_conversations_dir_is_noop(env) -> None:
    migrate(env.state_dir)  # no conversations/ created
    assert list_artifacts() == []


def test_registered_in_runner() -> None:
    from migrations._runner import _MIGRATIONS

    assert any(name == "010_backfill_artifacts_index" for name, _ in _MIGRATIONS)
