"""Unit tests for the artifacts index store."""

from __future__ import annotations

from pathlib import Path

from artifacts import (
    delete_artifact,
    list_artifacts,
    load_index,
    make_id,
    prune_missing,
    reconcile,
    record_artifact,
)


# ── identity ──────────────────────────────────────────────────────────────────

def test_make_id_is_deterministic_and_distinct() -> None:
    assert make_id("c1", "/p") == make_id("c1", "/p")
    assert make_id("c1", "/p") != make_id("c2", "/p")
    assert make_id("c1", "/p") != make_id("c1", "/q")


# ── record / upsert ───────────────────────────────────────────────────────────

def test_record_creates_entry(record_file) -> None:
    record_file("c1", "report.md", timestamp="2026-01-01T00:00:00")
    entries = list_artifacts()
    assert len(entries) == 1
    e = entries[0]
    assert e.conversation_id == "c1"
    assert e.filename == "report.md"
    assert e.content_type == "text/markdown"
    assert e.agent_name == "Claude"
    assert e.created_at == e.updated_at == "2026-01-01T00:00:00"


def test_record_dedupes_by_conversation_and_path(record_file) -> None:
    # Same (conv, path) twice — one entry; created_at preserved, updated_at bumped.
    record_file("c1", "report.md", timestamp="2026-01-01T00:00:00")
    record_file("c1", "report.md", timestamp="2026-01-02T00:00:00")
    entries = list_artifacts()
    assert len(entries) == 1
    assert entries[0].created_at == "2026-01-01T00:00:00"
    assert entries[0].updated_at == "2026-01-02T00:00:00"


def test_same_path_different_conversations_are_distinct(make_file) -> None:
    path = make_file("shared.md")
    for conv in ("c1", "c2"):
        record_artifact(
            conversation_id=conv, path=path, filename="shared.md",
            content_type="text/markdown", agent_name=None, sent_at="2026-01-01T00:00:00",
        )
    assert len(list_artifacts()) == 2


# ── list ──────────────────────────────────────────────────────────────────────

def test_list_filters_by_conversation(record_file) -> None:
    record_file("c1", "a.md", timestamp="2026-01-01T00:00:00")
    record_file("c2", "b.md", timestamp="2026-01-01T00:00:00")
    assert {e.conversation_id for e in list_artifacts("c1")} == {"c1"}
    assert len(list_artifacts("c1")) == 1
    assert len(list_artifacts()) == 2


def test_list_is_newest_first(record_file) -> None:
    record_file("c1", "old.md", timestamp="2026-01-01T00:00:00")
    record_file("c1", "new.md", timestamp="2026-02-01T00:00:00")
    assert [e.filename for e in list_artifacts()] == ["new.md", "old.md"]


# ── reconcile (non-destructive overlay) ───────────────────────────────────────

def test_reconcile_marks_present_and_missing_without_mutating(record_file) -> None:
    record_file("c1", "here.md", timestamp="2026-01-01T00:00:00")
    gone = record_file("c1", "gone.md", timestamp="2026-01-01T00:00:00")
    Path(gone).unlink()  # file vanishes after indexing

    viewed = {v.filename: v.status for v in reconcile(list_artifacts())}
    assert viewed == {"here.md": "present", "gone.md": "missing"}
    # The store is untouched — both entries still indexed.
    assert len(load_index().artifacts) == 2


def test_reconcile_marks_path_escaping_home_as_missing(vc_home) -> None:
    record_artifact(
        conversation_id="c1", path="/etc/passwd", filename="passwd",
        content_type="text/plain", agent_name=None, sent_at="2026-01-01T00:00:00",
    )
    assert reconcile(list_artifacts())[0].status == "missing"


# ── delete ────────────────────────────────────────────────────────────────────

def test_delete_entry_only_keeps_file(record_file) -> None:
    path = record_file("c1", "keep.md", timestamp="2026-01-01T00:00:00")
    assert delete_artifact(make_id("c1", path)) is True
    assert list_artifacts() == []
    assert Path(path).is_file()  # file left on disk


def test_delete_with_file_unlinks(record_file) -> None:
    path = record_file("c1", "remove.md", timestamp="2026-01-01T00:00:00")
    assert delete_artifact(make_id("c1", path), delete_file=True) is True
    assert list_artifacts() == []
    assert not Path(path).exists()


def test_delete_unknown_id_returns_false(vc_home) -> None:
    assert delete_artifact("nope") is False


# ── prune missing ─────────────────────────────────────────────────────────────

def test_prune_missing_removes_only_missing(record_file) -> None:
    record_file("c1", "here.md", timestamp="2026-01-01T00:00:00")
    gone = record_file("c1", "gone.md", timestamp="2026-01-01T00:00:00")
    Path(gone).unlink()

    assert prune_missing() == 1
    assert [e.filename for e in list_artifacts()] == ["here.md"]


def test_prune_missing_scoped_by_conversation(record_file) -> None:
    g1 = record_file("c1", "g1.md", timestamp="2026-01-01T00:00:00")
    g2 = record_file("c2", "g2.md", timestamp="2026-01-01T00:00:00")
    Path(g1).unlink()
    Path(g2).unlink()

    # Only c1's missing entry is pruned; c2's stays.
    assert prune_missing("c1") == 1
    assert {e.conversation_id for e in list_artifacts()} == {"c2"}


def test_prune_missing_keeps_present(record_file) -> None:
    record_file("c1", "here.md", timestamp="2026-01-01T00:00:00")
    assert prune_missing() == 0
    assert len(list_artifacts()) == 1
