"""Tests for migration 012 — rewrite old computron install paths to omnideck."""

from __future__ import annotations

from pathlib import Path

import pytest

from migrations._012_computron_path_rename import migrate

pytestmark = pytest.mark.unit

_NAME = "012_computron_path_rename"


def _backup_of(state_dir: Path, rel: str) -> Path:
    return state_dir / ".backups" / _NAME / rel


def test_rewrites_all_three_prefixes_in_nested_files(tmp_path: Path) -> None:
    skill = tmp_path / "skills" / "coder.json"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        '{"cwd": "/home/computron", "cache": "/var/lib/computron/x",'
        ' "app": "/opt/computron/server"}',
        encoding="utf-8",
    )
    events = tmp_path / "conversations" / "c1" / "events.jsonl"
    events.parent.mkdir(parents=True)
    events.write_text(
        '{"path": "/home/computron/Desktop/a.txt"}\n'
        '{"path": "/home/computron/downloads/b.txt"}\n',
        encoding="utf-8",
    )

    migrate(tmp_path)

    assert skill.read_text(encoding="utf-8") == (
        '{"cwd": "/home/omnideck", "cache": "/var/lib/omnideck/x",'
        ' "app": "/opt/omnideck/server"}'
    )
    assert events.read_text(encoding="utf-8") == (
        '{"path": "/home/omnideck/Desktop/a.txt"}\n'
        '{"path": "/home/omnideck/downloads/b.txt"}\n'
    )


def test_changed_file_is_backed_up_with_original_content(tmp_path: Path) -> None:
    f = tmp_path / "goals" / "g1.json"
    f.parent.mkdir(parents=True)
    original = '{"dir": "/home/computron/work"}'
    f.write_text(original, encoding="utf-8")

    migrate(tmp_path)

    backup = _backup_of(tmp_path, "goals/g1.json")
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == original


def test_noop_leaves_file_and_writes_no_backup(tmp_path: Path) -> None:
    f = tmp_path / "settings.json"
    before = '{"model": "opus", "path": "/home/omnideck/already"}'
    f.write_text(before, encoding="utf-8")

    migrate(tmp_path)

    assert f.read_text(encoding="utf-8") == before
    assert not (tmp_path / ".backups").exists()


def test_binary_file_is_skipped(tmp_path: Path) -> None:
    # A PNG-ish blob that also contains the old path bytes; the NUL marks it
    # binary so it must be left byte-for-byte identical.
    f = tmp_path / "static" / "logo.png"
    f.parent.mkdir(parents=True)
    blob = b"\x89PNG\x00\x00/home/computron/x\x00rest"
    f.write_bytes(blob)

    migrate(tmp_path)

    assert f.read_bytes() == blob
    assert not (tmp_path / ".backups").exists()


def test_non_utf8_text_file_is_skipped(tmp_path: Path) -> None:
    f = tmp_path / "weird.dat"
    blob = b"\xff\xfe/home/computron/x"  # invalid UTF-8, no NUL in probe
    f.write_bytes(blob)

    migrate(tmp_path)

    assert f.read_bytes() == blob
    assert not (tmp_path / ".backups").exists()


def test_backups_dir_is_not_rewritten(tmp_path: Path) -> None:
    # A prior migration's backup holds pre-rename content and must stay verbatim.
    backup = tmp_path / ".backups" / "008_something" / "conversations" / "c1" / "events.jsonl"
    backup.parent.mkdir(parents=True)
    original = '{"path": "/home/computron/keep"}'
    backup.write_text(original, encoding="utf-8")

    migrate(tmp_path)

    assert backup.read_text(encoding="utf-8") == original


def test_second_run_is_noop(tmp_path: Path) -> None:
    f = tmp_path / "sub_agents" / "p.json"
    f.parent.mkdir(parents=True)
    f.write_text('{"dir": "/home/computron/work"}', encoding="utf-8")

    migrate(tmp_path)
    after_first = f.read_text(encoding="utf-8")
    assert after_first == '{"dir": "/home/omnideck/work"}'

    migrate(tmp_path)
    assert f.read_text(encoding="utf-8") == after_first
    # The second run rewrites nothing, so it doesn't re-back-up the file: the
    # backup still holds the pre-rename original, not the rewritten content.
    assert _backup_of(tmp_path, "sub_agents/p.json").read_text(
        encoding="utf-8"
    ) == '{"dir": "/home/computron/work"}'
