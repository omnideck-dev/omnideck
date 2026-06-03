"""Tests for server._conversation_routes update handler (rename / pin)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from conversations._store import (
    load_conversation_metadata,
    save_conversation_history,
)
from server._conversation_routes import update_conversation_handler


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
    save_conversation_history(conv_id, [{"role": "user", "content": "hi"}])


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
