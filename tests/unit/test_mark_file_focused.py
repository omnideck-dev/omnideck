"""Tests for mark_file_focused — pre-focusing a file before reopen."""

from __future__ import annotations

from pathlib import Path

import pytest

from conversations._store import (
    mark_file_focused,
    load_preview_state,
    save_preview_state,
)


@pytest.fixture()
def _conv_dir(tmp_path: Path, monkeypatch) -> Path:
    """Point the conversation store at a temp directory."""
    conv_dir = tmp_path / "conversations"
    monkeypatch.setattr("conversations._store._get_conversations_dir", lambda: conv_dir)
    return conv_dir


@pytest.mark.unit
def test_sets_open_files_and_active_tab(_conv_dir: Path) -> None:
    """With no prior state, the file becomes the only open + active tab."""
    mark_file_focused("c1", "/home/computron/a.md")
    state = load_preview_state("c1")
    assert state["open_files"] == ["/home/computron/a.md"]
    assert state["active_tab"] == "file:/home/computron/a.md"


@pytest.mark.unit
def test_preserves_other_flags_and_open_files(_conv_dir: Path) -> None:
    """Merging adds the file + sets active without clobbering existing state."""
    save_preview_state("c1", {
        "open_files": ["/home/computron/old.html"],
        "active_tab": "file:/home/computron/old.html",
        "browser_visible": True,
        "terminal_visible": True,
        "desktop_visible": False,
        "generation_visible": False,
    })
    mark_file_focused("c1", "/home/computron/new.md")
    state = load_preview_state("c1")
    assert state["open_files"] == ["/home/computron/old.html", "/home/computron/new.md"]
    assert state["active_tab"] == "file:/home/computron/new.md"
    assert state["browser_visible"] is True
    assert state["terminal_visible"] is True
    assert state["desktop_visible"] is False


@pytest.mark.unit
def test_idempotent_no_duplicate(_conv_dir: Path) -> None:
    """Focusing the same file twice doesn't duplicate it in open_files."""
    mark_file_focused("c1", "/home/computron/a.md")
    mark_file_focused("c1", "/home/computron/a.md")
    state = load_preview_state("c1")
    assert state["open_files"] == ["/home/computron/a.md"]
    assert state["active_tab"] == "file:/home/computron/a.md"


@pytest.mark.unit
def test_recovers_from_malformed_open_files(_conv_dir: Path) -> None:
    """A non-list open_files is replaced, other flags survive."""
    save_preview_state("c1", {"open_files": "nonsense", "browser_visible": True})
    mark_file_focused("c1", "/home/computron/a.md")
    state = load_preview_state("c1")
    assert state["open_files"] == ["/home/computron/a.md"]
    assert state["browser_visible"] is True
