"""Tests for server._conversation_routes update handler (rename / pin)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import conversations._store as _store
from conversations._store import (
    conversation_exists,
    list_archived_conversations,
    load_conversation_metadata,
    save_conversation_title,
)
from server._conversation_routes import (
    archive_conversation_handler,
    generate_title_handler,
    list_archived_handler,
    unarchive_conversation_handler,
    update_conversation_handler,
)


@pytest.fixture()
def _conv_dir(tmp_path: Path, monkeypatch) -> Path:
    """Point the conversation store at a temp directory."""
    conv_dir = tmp_path / "conversations"
    monkeypatch.setattr(
        "conversations._store._get_conversations_dir",
        lambda: conv_dir,
    )
    return conv_dir


def _make_request(conversation_id: str, json_body) -> MagicMock:
    """Build a minimal aiohttp.web.Request-ish double."""
    req = MagicMock()
    req.match_info = {"conversation_id": conversation_id}
    req.json = AsyncMock(return_value=json_body)
    return req


def _seed(conv_id: str) -> None:
    """Create a minimal event log so the conversation exists on disk."""
    d = _store._get_conversations_dir() / conv_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "events.jsonl").write_text(json.dumps({
        "id": f"evt_{conv_id}", "type": "agent_started",
        "timestamp": "2026-01-01T00:00:00", "conversation_id": conv_id,
        "agent_id": "root.test.1", "agent_name": "TEST",
        "parent_agent_id": None,
    }) + "\n")


@pytest.mark.unit
class TestUpdateConversation:
    """PATCH /api/conversations/sessions/{id}."""

    async def test_rename(self, _conv_dir: Path) -> None:
        """A title in the body is persisted to metadata."""
        _seed("c1")
        resp = await update_conversation_handler(_make_request("c1", {"title": "Renamed"}))
        assert resp.status == 204
        assert load_conversation_metadata("c1")["title"] == "Renamed"

    async def test_rename_trims_and_caps_length(self, _conv_dir: Path) -> None:
        """Titles are stripped and capped at the 50-char limit."""
        _seed("c1")
        await update_conversation_handler(
            _make_request("c1", {"title": "   " + "x" * 80 + "   "}),
        )
        assert load_conversation_metadata("c1")["title"] == "x" * 50

    async def test_blank_title_is_persisted(self, _conv_dir: Path) -> None:
        """A blank title is stored (the UI renders the first-message fallback)."""
        _seed("c1")
        resp = await update_conversation_handler(_make_request("c1", {"title": "   "}))
        assert resp.status == 204
        assert load_conversation_metadata("c1")["title"] == ""

    async def test_pin(self, _conv_dir: Path) -> None:
        """A pinned flag in the body is persisted to metadata."""
        _seed("c1")
        resp = await update_conversation_handler(_make_request("c1", {"pinned": True}))
        assert resp.status == 204
        assert load_conversation_metadata("c1")["pinned"] is True

    async def test_rename_and_pin_together(self, _conv_dir: Path) -> None:
        """Title and pin can be set in a single request."""
        _seed("c1")
        await update_conversation_handler(
            _make_request("c1", {"title": "Both", "pinned": True}),
        )
        meta = load_conversation_metadata("c1")
        assert meta["title"] == "Both"
        assert meta["pinned"] is True

    async def test_missing_conversation_404(self, _conv_dir: Path) -> None:
        """Updating an unknown conversation is a 404 and writes nothing."""
        resp = await update_conversation_handler(_make_request("ghost", {"title": "x"}))
        assert resp.status == 404
        assert load_conversation_metadata("ghost") == {}

    async def test_non_dict_body_400(self, _conv_dir: Path) -> None:
        """A non-object JSON body is rejected."""
        _seed("c1")
        resp = await update_conversation_handler(_make_request("c1", ["not", "a", "dict"]))
        assert resp.status == 400

    async def test_invalid_pinned_type_400(self, _conv_dir: Path) -> None:
        """A non-boolean pinned value is rejected."""
        _seed("c1")
        resp = await update_conversation_handler(_make_request("c1", {"pinned": "yes"}))
        assert resp.status == 400

    async def test_invalid_title_type_400(self, _conv_dir: Path) -> None:
        """A non-string title value is rejected."""
        _seed("c1")
        resp = await update_conversation_handler(_make_request("c1", {"title": 123}))
        assert resp.status == 400


@pytest.mark.unit
class TestArchiveRoutes:
    """POST archive/unarchive and GET archived listing."""

    async def test_archive_moves_conversation(self, _conv_dir: Path) -> None:
        """Archiving succeeds and the conversation leaves the active store."""
        _seed("c1")
        resp = await archive_conversation_handler(_make_request("c1", None))
        assert resp.status == 204
        assert conversation_exists("c1") is False
        assert [s.conversation_id for s in list_archived_conversations()] == ["c1"]

    async def test_archive_missing_404(self, _conv_dir: Path) -> None:
        """Archiving an unknown conversation is a 404."""
        resp = await archive_conversation_handler(_make_request("ghost", None))
        assert resp.status == 404

    async def test_unarchive_restores_conversation(self, _conv_dir: Path) -> None:
        """Restoring brings the conversation back into the active store."""
        _seed("c1")
        await archive_conversation_handler(_make_request("c1", None))
        resp = await unarchive_conversation_handler(_make_request("c1", None))
        assert resp.status == 204
        assert conversation_exists("c1") is True
        assert list_archived_conversations() == []

    async def test_unarchive_missing_404(self, _conv_dir: Path) -> None:
        """Restoring an unknown archived conversation is a 404."""
        resp = await unarchive_conversation_handler(_make_request("ghost", None))
        assert resp.status == 404

    async def test_list_archived(self, _conv_dir: Path) -> None:
        """The archived listing returns summaries of archived conversations."""
        _seed("c1")
        await archive_conversation_handler(_make_request("c1", None))
        resp = await list_archived_handler(_make_request("", None))
        assert resp.status == 200
        data = json.loads(resp.body)
        assert [row["conversation_id"] for row in data] == ["c1"]


@pytest.mark.unit
class TestGenerateTitle:
    """POST /api/conversations/sessions/{id}/title."""

    async def test_generates_and_saves(self, _conv_dir: Path, monkeypatch) -> None:
        """The first message is turned into a title, persisted, and returned."""
        gen = AsyncMock(return_value="A Snappy Title")
        monkeypatch.setattr(
            "server._conversation_routes.generate_conversation_title", gen,
        )
        resp = await generate_title_handler(
            _make_request("c1", {"first_message": "how do I flush the muxer"}),
        )
        assert resp.status == 200
        assert json.loads(resp.body)["title"] == "A Snappy Title"
        assert load_conversation_metadata("c1")["title"] == "A Snappy Title"
        gen.assert_awaited_once_with("how do I flush the muxer")

    async def test_idempotent_keeps_existing_title(self, _conv_dir: Path, monkeypatch) -> None:
        """An existing title (e.g. a manual rename) is returned, not regenerated."""
        save_conversation_title("c1", "User Named This")
        gen = AsyncMock(return_value="Generated Instead")
        monkeypatch.setattr(
            "server._conversation_routes.generate_conversation_title", gen,
        )
        resp = await generate_title_handler(
            _make_request("c1", {"first_message": "hello"}),
        )
        assert resp.status == 200
        assert json.loads(resp.body)["title"] == "User Named This"
        assert load_conversation_metadata("c1")["title"] == "User Named This"
        gen.assert_not_awaited()

    async def test_blank_first_message_400(self, _conv_dir: Path, monkeypatch) -> None:
        """A blank first message is rejected and no generation runs."""
        gen = AsyncMock(return_value="x")
        monkeypatch.setattr(
            "server._conversation_routes.generate_conversation_title", gen,
        )
        resp = await generate_title_handler(_make_request("c1", {"first_message": "   "}))
        assert resp.status == 400
        gen.assert_not_awaited()

    async def test_missing_first_message_400(self, _conv_dir: Path) -> None:
        """A body without first_message is rejected."""
        resp = await generate_title_handler(_make_request("c1", {}))
        assert resp.status == 400

    async def test_non_dict_body_400(self, _conv_dir: Path) -> None:
        """A non-object JSON body is rejected."""
        resp = await generate_title_handler(_make_request("c1", ["nope"]))
        assert resp.status == 400

    async def test_generation_failure_502_writes_nothing(self, _conv_dir: Path, monkeypatch) -> None:
        """If generation raises, the endpoint reports 502 and saves no title."""
        gen = AsyncMock(side_effect=RuntimeError("model unavailable"))
        monkeypatch.setattr(
            "server._conversation_routes.generate_conversation_title", gen,
        )
        resp = await generate_title_handler(
            _make_request("c1", {"first_message": "hello"}),
        )
        assert resp.status == 502
        assert load_conversation_metadata("c1") == {}
