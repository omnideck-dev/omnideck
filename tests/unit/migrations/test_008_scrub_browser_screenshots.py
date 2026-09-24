"""Tests for migration 008 — scrub browser_screenshot events from events.jsonl."""

from __future__ import annotations

import json
from pathlib import Path

from migrations._008_scrub_browser_screenshots import migrate


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


def _shot(tab_id: str, screenshot: str, ts: str) -> dict:
    return {
        "id": f"evt_{screenshot}", "type": "browser_screenshot", "timestamp": ts,
        "conversation_id": "c1", "agent_id": "root.a.1",
        "url": f"https://{screenshot}.example", "title": screenshot,
        "screenshot": screenshot, "tab_id": tab_id,
    }


def test_strips_screenshots_and_keeps_latest_per_tab(tmp_path: Path) -> None:
    conv = tmp_path / "conversations" / "c1"
    _write_log(conv, [
        {"id": "e1", "type": "user_message", "content": "hi", "agent_id": "root.a.1"},
        _shot("t1", "old", "2026-01-01T00:00:01+00:00"),
        _shot("t1", "new", "2026-01-01T00:00:02+00:00"),
        _shot("t2", "only", "2026-01-01T00:00:03+00:00"),
        {"id": "e2", "type": "iteration", "content": "done", "agent_id": "root.a.1"},
    ])

    migrate(tmp_path)

    types = [e["type"] for e in _read_log(conv)]
    assert types == ["user_message", "iteration"]

    tabs = json.loads((conv / "browser_tabs.json").read_text(encoding="utf-8"))
    assert set(tabs) == {"t1", "t2"}
    assert tabs["t1"]["screenshot"] == "new"
    assert tabs["t2"]["screenshot"] == "only"

    # Original log was backed up before the rewrite.
    backup = tmp_path / ".backups" / "008_scrub_browser_screenshots" / "conversations" / "c1" / "events.jsonl"
    assert backup.exists()
    assert "browser_screenshot" in backup.read_text(encoding="utf-8")


def test_noop_for_logs_without_screenshots(tmp_path: Path) -> None:
    conv = tmp_path / "conversations" / "clean"
    _write_log(conv, [
        {"id": "e1", "type": "user_message", "content": "hi", "agent_id": "root.a.1"},
    ])
    before = (conv / "events.jsonl").read_text(encoding="utf-8")

    migrate(tmp_path)

    assert (conv / "events.jsonl").read_text(encoding="utf-8") == before
    assert not (conv / "browser_tabs.json").exists()
    assert not (tmp_path / ".backups").exists()


def test_existing_sidecar_entries_win_over_log_derived(tmp_path: Path) -> None:
    """A sidecar written live since the upgrade is newer than the log."""
    conv = tmp_path / "conversations" / "c1"
    _write_log(conv, [_shot("t1", "stale-from-log", "2026-01-01T00:00:01+00:00")])
    (conv / "browser_tabs.json").write_text(json.dumps({
        "t1": {"tab_id": "t1", "url": "https://live.example", "title": "live",
               "screenshot": "fresh-live", "agent_id": "root.a.2",
               "timestamp": "2026-01-02T00:00:00+00:00"},
    }), encoding="utf-8")

    migrate(tmp_path)

    tabs = json.loads((conv / "browser_tabs.json").read_text(encoding="utf-8"))
    assert tabs["t1"]["screenshot"] == "fresh-live"
    assert _read_log(conv) == []


def test_missing_conversations_dir_is_noop(tmp_path: Path) -> None:
    migrate(tmp_path)  # must not raise
