"""Tests for the focus-file conversation route (POST .../preview-state/focus-file)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import conversations._store as _store
from conversations._store import load_preview_state
from server._conversation_routes import focus_file_handler


@pytest.fixture()
def _conv_dir(tmp_path: Path, monkeypatch) -> Path:
    """Point the conversation store at a temp directory."""
    conv_dir = tmp_path / "conversations"
    monkeypatch.setattr("conversations._store._get_conversations_dir", lambda: conv_dir)
    return conv_dir


def _seed(conv_id: str) -> None:
    """Create a minimal event log so the conversation exists on disk."""
    d = _store._get_conversations_dir() / conv_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "events.jsonl").write_text(json.dumps({
        "id": f"evt_{conv_id}", "type": "agent_started",
        "timestamp": "2026-01-01T00:00:00", "conversation_id": conv_id,
        "agent_id": "root.test.1", "agent_name": "TEST", "parent_agent_id": None,
    }) + "\n")


def _make_request(conversation_id: str, json_body) -> MagicMock:
    """Build a minimal aiohttp.web.Request-ish double."""
    req = MagicMock()
    req.match_info = {"conversation_id": conversation_id}
    req.json = AsyncMock(return_value=json_body)
    return req


@pytest.mark.unit
async def test_persists_and_returns_204(_conv_dir: Path) -> None:
    """A valid request focuses the file and returns 204."""
    _seed("c1")
    resp = await focus_file_handler(_make_request("c1", {"path": "/home/computron/a.md"}))
    assert resp.status == 204
    state = load_preview_state("c1")
    assert state["active_tab"] == "file:/home/computron/a.md"
    assert "/home/computron/a.md" in state["open_files"]


@pytest.mark.unit
async def test_missing_conversation_404(_conv_dir: Path) -> None:
    """Focusing in an unknown conversation is a 404 and writes nothing."""
    resp = await focus_file_handler(_make_request("ghost", {"path": "/home/computron/a.md"}))
    assert resp.status == 404
    assert load_preview_state("ghost") == {}


@pytest.mark.unit
async def test_missing_path_400(_conv_dir: Path) -> None:
    """A body without a path string is rejected."""
    _seed("c1")
    resp = await focus_file_handler(_make_request("c1", {}))
    assert resp.status == 400


@pytest.mark.unit
async def test_non_dict_body_400(_conv_dir: Path) -> None:
    """A non-object JSON body is rejected."""
    _seed("c1")
    resp = await focus_file_handler(_make_request("c1", ["nope"]))
    assert resp.status == 400
