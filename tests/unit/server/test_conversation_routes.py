"""Tests for server._conversation_routes update handler (rename / pin)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import conversations._store as _store
from agent_runtime import RunSnapshot
from conversations import ConversationResumeState
from conversations._folders import create_folder, list_folders
from conversations._store import (
    conversation_exists,
    list_archived_conversations,
    load_conversation_metadata,
    save_conversation_title,
)
from server._agent_runtime import AGENT_RUNTIME_KEY
from server._conversation_routes import (
    archive_conversation_handler,
    create_folder_handler,
    delete_conversation_handler,
    delete_folder_handler,
    generate_title_handler,
    list_archived_handler,
    list_folders_handler,
    resume_conversation_handler,
    unarchive_conversation_handler,
    update_conversation_handler,
    update_folder_handler,
)


@pytest.fixture()
def _conv_dir(tmp_path: Path, monkeypatch) -> Path:
    """Point the conversation store and folder registry at a temp directory."""
    conv_dir = tmp_path / "conversations"
    monkeypatch.setattr(
        "conversations._store._get_conversations_dir",
        lambda: conv_dir,
    )
    monkeypatch.setattr(
        "conversations._folders._folders_path",
        lambda: conv_dir / "_folders.json",
    )
    return conv_dir


def _make_request(
    conversation_id: str,
    json_body,
    *,
    active_run_manager: MagicMock | None = None,
) -> MagicMock:
    """Build a minimal aiohttp.web.Request-ish double."""
    req = MagicMock()
    req.match_info = {"conversation_id": conversation_id}
    req.json = AsyncMock(return_value=json_body)
    manager = active_run_manager or MagicMock()
    if active_run_manager is None:
        manager.active_for_conversation.return_value = None
    req.app = {AGENT_RUNTIME_KEY: manager}
    return req


def _make_folder_request(folder_id: str, json_body) -> MagicMock:
    """Build a request double whose match_info carries a folder_id."""
    req = MagicMock()
    req.match_info = {"folder_id": folder_id}
    req.json = AsyncMock(return_value=json_body)
    return req


def _seed(conv_id: str) -> None:
    """Create a minimal event log so the conversation exists on disk."""
    d = _store._get_conversations_dir() / conv_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "events.jsonl").write_text(
        json.dumps(
            {
                "id": f"evt_{conv_id}",
                "type": "agent_started",
                "timestamp": "2026-01-01T00:00:00",
                "conversation_id": conv_id,
                "agent_id": "root.test.1",
                "agent_name": "TEST",
                "parent_agent_id": None,
            }
        )
        + "\n"
    )


@pytest.mark.unit
async def test_resume_route_returns_workspace_sidecars(monkeypatch) -> None:
    """The HTTP payload includes the explicit browser and terminal restores."""
    resume = AsyncMock(
        return_value=ConversationResumeState(
            messages=[],
            events=[{"id": "event-1", "type": "agent_started"}],
            browser_tabs=[{"tab_id": 1, "agent_id": "root-1"}],
            terminal={"root-1": [{"cmd_id": "command-1"}]},
            preview_state={"active_tab": "browser"},
            profile_id="general",
        )
    )
    monkeypatch.setattr(
        "server._conversation_routes.load_conversation_resume_state",
        resume,
    )
    monkeypatch.setattr("server._conversation_routes.conversation_exists", lambda _id: True)

    response = await resume_conversation_handler(_make_request("conversation-1", None))
    body = json.loads(response.body)

    assert body["browser_tabs"] == [{"tab_id": 1, "agent_id": "root-1"}]
    assert body["terminal"] == {"root-1": [{"cmd_id": "command-1"}]}
    assert body["active_run"] is None
    resume.assert_awaited_once_with("conversation-1")


@pytest.mark.unit
async def test_resume_route_returns_404_for_unknown_conversation(monkeypatch) -> None:
    """A missing conversation without an active run cannot be resumed."""
    resume = AsyncMock()
    monkeypatch.setattr(
        "server._conversation_routes.load_conversation_resume_state",
        resume,
    )
    monkeypatch.setattr("server._conversation_routes.conversation_exists", lambda _id: False)

    response = await resume_conversation_handler(_make_request("missing", None))

    assert response.status == 404
    resume.assert_not_awaited()


@pytest.mark.unit
async def test_resume_route_returns_active_run_at_persisted_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cursor identifies the newest snapshot event from the active run."""
    resume = AsyncMock(
        return_value=ConversationResumeState(
            messages=[],
            events=[
                {"id": "old-event", "type": "iteration"},
                {"id": "run-started", "type": "agent_started"},
                {"id": "run-user", "type": "user_message"},
            ],
            browser_tabs=[],
            terminal={},
            preview_state={},
            profile_id="general",
        )
    )
    monkeypatch.setattr(
        "server._conversation_routes.load_conversation_resume_state",
        resume,
    )
    manager = MagicMock()
    handle = manager.active_for_conversation.return_value
    handle.run_id = "run-1"
    handle.snapshot.return_value = RunSnapshot(
        status="running",
        run_id="run-1",
        conversation_id="conversation-1",
        last_seq=8,
    )
    handle.sequence_for_event.side_effect = lambda event_id: {
        "run-user": 3,
        "run-started": 1,
    }.get(event_id)

    response = await resume_conversation_handler(
        _make_request(
            "conversation-1",
            None,
            active_run_manager=manager,
        )
    )
    body = json.loads(response.body)

    assert body["active_run"] == {
        "run_id": "run-1",
        "status": "running",
        "last_seq": 8,
        "resume_after_seq": 3,
    }
    resume.assert_awaited_once_with("conversation-1")
    handle.sequence_for_event.assert_called_once_with("run-user")


@pytest.mark.unit
async def test_resume_route_returns_active_run_before_first_persisted_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A just-reserved run is discoverable with a cursor of zero."""
    resume = AsyncMock(
        return_value=ConversationResumeState(
            messages=[],
            events=[],
            browser_tabs=[],
            terminal={},
            preview_state={},
            profile_id=None,
        )
    )
    monkeypatch.setattr(
        "server._conversation_routes.load_conversation_resume_state",
        resume,
    )
    manager = MagicMock()
    handle = manager.active_for_conversation.return_value
    handle.run_id = "run-new"
    handle.snapshot.return_value = RunSnapshot(
        status="running",
        run_id="run-new",
        conversation_id="conversation-new",
        last_seq=0,
    )

    response = await resume_conversation_handler(
        _make_request(
            "conversation-new",
            None,
            active_run_manager=manager,
        )
    )
    body = json.loads(response.body)

    assert body["active_run"]["run_id"] == "run-new"
    assert body["active_run"]["resume_after_seq"] == 0


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
class TestFolderRoutes:
    """Folder CRUD endpoints and folder_id on the conversation PATCH."""

    async def test_create_folder(self, _conv_dir: Path) -> None:
        """Creating a folder returns 201 with the created folder."""
        resp = await create_folder_handler(_make_folder_request("", {"name": "Work"}))
        assert resp.status == 201
        body = json.loads(resp.body)
        assert body["name"] == "Work"
        assert body["id"]
        assert [f.name for f in list_folders()] == ["Work"]

    async def test_create_folder_blank_name_400(self, _conv_dir: Path) -> None:
        """A blank folder name is rejected."""
        resp = await create_folder_handler(_make_folder_request("", {"name": "  "}))
        assert resp.status == 400

    async def test_list_folders(self, _conv_dir: Path) -> None:
        """The listing returns created folders."""
        create_folder("Work")
        create_folder("Play")
        resp = await list_folders_handler(_make_folder_request("", None))
        assert resp.status == 200
        assert [f["name"] for f in json.loads(resp.body)] == ["Work", "Play"]

    async def test_update_folder_renames(self, _conv_dir: Path) -> None:
        """Renaming a folder persists the new name."""
        folder = create_folder("Draft")
        resp = await update_folder_handler(
            _make_folder_request(folder.id, {"name": "Final"}),
        )
        assert resp.status == 200
        assert json.loads(resp.body)["name"] == "Final"

    async def test_update_folder_missing_404(self, _conv_dir: Path) -> None:
        """Updating an unknown folder is a 404."""
        resp = await update_folder_handler(_make_folder_request("nope", {"name": "x"}))
        assert resp.status == 404

    async def test_update_folder_sets_icon(self, _conv_dir: Path) -> None:
        """A valid bootstrap icon class is persisted."""
        folder = create_folder("Work")
        resp = await update_folder_handler(
            _make_folder_request(folder.id, {"icon": "bi-briefcase"}),
        )
        assert resp.status == 200
        assert json.loads(resp.body)["icon"] == "bi-briefcase"

    async def test_update_folder_bad_icon_400(self, _conv_dir: Path) -> None:
        """A value that isn't a bootstrap icon class is rejected."""
        folder = create_folder("Work")
        resp = await update_folder_handler(
            _make_folder_request(folder.id, {"icon": "bi-x' onload=alert(1)"}),
        )
        assert resp.status == 400

    async def test_delete_folder_unfiles_members(self, _conv_dir: Path) -> None:
        """Deleting a folder removes it and clears it from member conversations."""
        folder = create_folder("Work")
        _seed("c1")
        _store.save_conversation_folder("c1", folder.id)

        resp = await delete_folder_handler(_make_folder_request(folder.id, None))
        assert resp.status == 204
        assert list_folders() == []
        assert load_conversation_metadata("c1")["folder_id"] is None

    async def test_delete_folder_missing_404(self, _conv_dir: Path) -> None:
        """Deleting an unknown folder is a 404."""
        resp = await delete_folder_handler(_make_folder_request("nope", None))
        assert resp.status == 404

    async def test_patch_conversation_files_into_folder(self, _conv_dir: Path) -> None:
        """Filing a conversation via its PATCH endpoint sets its folder_id."""
        folder = create_folder("Work")
        _seed("c1")
        resp = await update_conversation_handler(
            _make_request("c1", {"folder_id": folder.id}),
        )
        assert resp.status == 204
        assert load_conversation_metadata("c1")["folder_id"] == folder.id

    async def test_patch_conversation_unknown_folder_400(self, _conv_dir: Path) -> None:
        """An unknown folder_id is rejected and nothing is written."""
        _seed("c1")
        resp = await update_conversation_handler(
            _make_request("c1", {"folder_id": "ghost"}),
        )
        assert resp.status == 400
        assert "folder_id" not in load_conversation_metadata("c1")

    async def test_patch_conversation_clears_folder(self, _conv_dir: Path) -> None:
        """A null folder_id removes the conversation from its folder."""
        folder = create_folder("Work")
        _seed("c1")
        _store.save_conversation_folder("c1", folder.id)
        resp = await update_conversation_handler(
            _make_request("c1", {"folder_id": None}),
        )
        assert resp.status == 204
        assert load_conversation_metadata("c1")["folder_id"] is None


@pytest.mark.unit
class TestArchiveRoutes:
    """POST archive/unarchive and GET archived listing."""

    async def test_archive_moves_conversation(self, _conv_dir: Path, monkeypatch) -> None:
        """Archiving succeeds and the conversation leaves the active store."""
        evict = AsyncMock()
        monkeypatch.setattr("server._conversation_routes.evict_conversation", evict)
        _seed("c1")
        resp = await archive_conversation_handler(_make_request("c1", None))
        assert resp.status == 204
        assert conversation_exists("c1") is False
        assert [s.conversation_id for s in list_archived_conversations()] == ["c1"]
        evict.assert_awaited_once_with("c1")

    async def test_archive_missing_404(self, _conv_dir: Path) -> None:
        """Archiving an unknown conversation is a 404."""
        resp = await archive_conversation_handler(_make_request("ghost", None))
        assert resp.status == 404

    async def test_archive_active_conversation_409(self, _conv_dir: Path) -> None:
        """Archiving cannot move storage while its run is still writing."""
        _seed("c1")
        manager = MagicMock()
        manager.active_for_conversation.return_value = object()

        resp = await archive_conversation_handler(
            _make_request("c1", None, active_run_manager=manager),
        )

        assert resp.status == 409
        assert json.loads(resp.body) == {
            "error": "This conversation is still running. Stop it before archiving.",
        }
        assert conversation_exists("c1") is True
        assert list_archived_conversations() == []

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
async def test_delete_active_conversation_409(_conv_dir: Path) -> None:
    """Deleting cannot remove storage while its run is still writing."""
    _seed("c1")
    manager = MagicMock()
    manager.active_for_conversation.return_value = object()

    resp = await delete_conversation_handler(
        _make_request("c1", None, active_run_manager=manager),
    )

    assert resp.status == 409
    assert json.loads(resp.body) == {
        "error": "This conversation is still running. Stop it before deleting.",
    }
    assert conversation_exists("c1") is True


@pytest.mark.unit
async def test_delete_evicts_live_conversation_resources(_conv_dir: Path, monkeypatch) -> None:
    """Deleting persisted history also releases cached runtime resources."""
    evict = AsyncMock()
    monkeypatch.setattr("server._conversation_routes.evict_conversation", evict)
    _seed("c1")

    response = await delete_conversation_handler(_make_request("c1", None))

    assert response.status == 204
    assert conversation_exists("c1") is False
    evict.assert_awaited_once_with("c1")


@pytest.mark.unit
class TestGenerateTitle:
    """POST /api/conversations/sessions/{id}/title."""

    async def test_generates_and_saves(self, _conv_dir: Path, monkeypatch) -> None:
        """The first message is turned into a title, persisted, and returned."""
        gen = AsyncMock(return_value="A Snappy Title")
        monkeypatch.setattr(
            "server._conversation_routes.generate_conversation_title",
            gen,
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
            "server._conversation_routes.generate_conversation_title",
            gen,
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
            "server._conversation_routes.generate_conversation_title",
            gen,
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
            "server._conversation_routes.generate_conversation_title",
            gen,
        )
        resp = await generate_title_handler(
            _make_request("c1", {"first_message": "hello"}),
        )
        assert resp.status == 502
        assert load_conversation_metadata("c1") == {}
