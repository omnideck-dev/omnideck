"""Unit tests for conversation persistence store."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from conversations._store import (
    archive_conversation,
    conversation_exists,
    delete_conversation,
    list_archived_conversations,
    list_conversations,
    load_conversation_metadata,
    load_conversation_profile,
    save_conversation_pinned,
    save_conversation_profile,
    save_conversation_title,
    unarchive_conversation,
)


@pytest.fixture()
def _conv_dir(tmp_path: Path) -> Path:
    """Patch the conversations directory to a temp directory."""
    conv_dir = tmp_path / "conversations"
    with patch(
        "conversations._store._get_conversations_dir",
        return_value=conv_dir,
    ):
        yield conv_dir


def _seed_events_jsonl(
    conv_dir: Path, conv_id: str, messages: list[dict],
) -> None:
    """Write an events.jsonl whose root-agent user_message events match
    the supplied message list."""
    agent_id = "root.test.1"
    d = conv_dir / conv_id
    d.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({
        "id": f"evt_{conv_id}_started", "type": "agent_started",
        "timestamp": "2026-01-01T00:00:00",
        "conversation_id": conv_id, "agent_id": agent_id,
        "agent_name": "TEST", "parent_agent_id": None,
    })]
    for i, m in enumerate(messages, start=1):
        if m.get("role") != "user":
            continue
        lines.append(json.dumps({
            "id": f"evt_{conv_id}_{i}", "type": "user_message",
            "timestamp": f"2026-01-01T00:00:{i:02d}",
            "conversation_id": conv_id, "agent_id": agent_id,
            "content": m.get("content", ""), "attachments": [],
        }))
    (d / "events.jsonl").write_text("\n".join(lines) + "\n")


@pytest.mark.unit
class TestListConversations:
    """Tests for conversation listing."""

    def test_list_conversations(self, _conv_dir: Path) -> None:
        """List conversations from subdirectories.

        Recognition is based on ``events.jsonl`` presence; turn count
        and first message are derived from root-agent ``user_message``
        events.
        """
        _seed_events_jsonl(_conv_dir, "conv-1", [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "bye"},
        ])
        _seed_events_jsonl(_conv_dir, "conv-2", [
            {"role": "user", "content": "search for flights"},
        ])

        summaries = list_conversations()
        assert len(summaries) == 2
        by_id = {s.conversation_id: s for s in summaries}
        assert by_id["conv-1"].turn_count == 2
        assert by_id["conv-1"].first_message == "hello"
        assert by_id["conv-2"].turn_count == 1

    def test_list_empty(self, _conv_dir: Path) -> None:
        """Listing with no conversations returns empty list."""
        assert list_conversations() == []

    def test_started_at_is_first_event_timestamp_not_file_mtime(
        self, _conv_dir: Path,
    ) -> None:
        """started_at must come from the first event in events.jsonl, not
        the file's mtime. mtime advances every time we append a new event,
        which would dump every active conversation into the Today bucket.
        """
        _seed_events_jsonl(_conv_dir, "old-conv", [
            {"role": "user", "content": "hi"},
        ])
        # Touch the file far into the future to simulate recent activity
        # on an old conversation. The summary should still report the
        # first event's timestamp, not now.
        import os
        future = 9999999999  # year ~2286
        os.utime(
            _conv_dir / "old-conv" / "events.jsonl",
            (future, future),
        )
        summaries = list_conversations()
        # First event in events.jsonl is the agent_started at :00; the
        # first user_message follows at :01. started_at is the very first
        # event timestamp.
        assert summaries[0].started_at == "2026-01-01T00:00:00"

    def test_recency_sort_uses_first_event_timestamp(
        self, _conv_dir: Path,
    ) -> None:
        """Sort is by first event timestamp descending, regardless of
        which file was written last."""
        _seed_events_jsonl(_conv_dir, "old", [
            {"role": "user", "content": "old"},
        ])
        # Override "old" conv to be earlier. started_at is the FIRST event
        # (the agent_started at :00), so shift the whole date — shifting
        # only the user_message (:01) would leave both convs tied on
        # started_at and the sort order would be arbitrary.
        old_path = _conv_dir / "old" / "events.jsonl"
        old_path.write_text(old_path.read_text().replace(
            "2026-01-01", "2025-01-01",
        ))
        _seed_events_jsonl(_conv_dir, "new", [
            {"role": "user", "content": "new"},
        ])
        ids = [s.conversation_id for s in list_conversations()]
        assert ids == ["new", "old"]


@pytest.mark.unit
class TestDeleteConversation:
    """Tests for conversation deletion."""

    def test_delete(self, _conv_dir: Path) -> None:
        """Delete removes the entire conversation directory."""
        _seed_events_jsonl(_conv_dir, "conv-1", [{"role": "user", "content": "hi"}])
        assert delete_conversation("conv-1") is True
        assert not (_conv_dir / "conv-1").exists()

    def test_delete_nonexistent(self, _conv_dir: Path) -> None:
        """Deleting a missing conversation returns False."""
        assert delete_conversation("nope") is False


@pytest.mark.unit
class TestArchiveConversation:
    """Tests for archiving, restoring, and listing archived conversations."""

    def test_archive_removes_from_active_list(self, _conv_dir: Path) -> None:
        """An archived conversation drops out of the active listing."""
        _seed_events_jsonl(_conv_dir, "conv-1", [{"role": "user", "content": "hi"}])
        _seed_events_jsonl(_conv_dir, "conv-2", [{"role": "user", "content": "yo"}])
        assert archive_conversation("conv-1") is True

        active_ids = {s.conversation_id for s in list_conversations()}
        assert active_ids == {"conv-2"}

    def test_archived_appears_in_archived_list(self, _conv_dir: Path) -> None:
        """An archived conversation surfaces in the archived listing."""
        _seed_events_jsonl(_conv_dir, "conv-1", [{"role": "user", "content": "hi"}])
        archive_conversation("conv-1")

        archived = list_archived_conversations()
        assert [s.conversation_id for s in archived] == ["conv-1"]
        assert archived[0].first_message == "hi"

    def test_archived_dir_not_listed_as_conversation(self, _conv_dir: Path) -> None:
        """The reserved archive folder is never treated as a conversation."""
        _seed_events_jsonl(_conv_dir, "conv-1", [{"role": "user", "content": "hi"}])
        archive_conversation("conv-1")
        # The active list is empty even though the _archived dir exists on disk.
        assert list_conversations() == []

    def test_archive_preserves_metadata(self, _conv_dir: Path) -> None:
        """Title and pinned flag travel with the archived conversation."""
        _seed_events_jsonl(_conv_dir, "conv-1", [{"role": "user", "content": "hi"}])
        save_conversation_title("conv-1", "My Title")
        save_conversation_pinned("conv-1", True)
        archive_conversation("conv-1")

        archived = list_archived_conversations()[0]
        assert archived.title == "My Title"
        assert archived.pinned is True

    def test_unarchive_restores_to_active_list(self, _conv_dir: Path) -> None:
        """Restoring moves a conversation back into the active listing."""
        _seed_events_jsonl(_conv_dir, "conv-1", [{"role": "user", "content": "hi"}])
        archive_conversation("conv-1")
        assert unarchive_conversation("conv-1") is True

        assert [s.conversation_id for s in list_conversations()] == ["conv-1"]
        assert list_archived_conversations() == []
        assert conversation_exists("conv-1") is True

    def test_archive_missing_returns_false(self, _conv_dir: Path) -> None:
        """Archiving an unknown conversation returns False."""
        assert archive_conversation("nope") is False

    def test_unarchive_missing_returns_false(self, _conv_dir: Path) -> None:
        """Restoring an unknown archived conversation returns False."""
        assert unarchive_conversation("nope") is False

    def test_delete_removes_archived_conversation(self, _conv_dir: Path) -> None:
        """Delete also reaches conversations that have been archived."""
        _seed_events_jsonl(_conv_dir, "conv-1", [{"role": "user", "content": "hi"}])
        archive_conversation("conv-1")
        assert delete_conversation("conv-1") is True
        assert list_archived_conversations() == []


@pytest.mark.unit
class TestConversationExists:
    """Tests for the on-disk existence check."""

    def test_exists_after_seed(self, _conv_dir: Path) -> None:
        """A conversation with a persisted event log reports as existing."""
        _seed_events_jsonl(_conv_dir, "conv-1", [{"role": "user", "content": "hi"}])
        assert conversation_exists("conv-1") is True

    def test_missing(self, _conv_dir: Path) -> None:
        """An unknown conversation does not exist."""
        assert conversation_exists("nope") is False

    def test_metadata_only_does_not_count(self, _conv_dir: Path) -> None:
        """Metadata without an event log is not a real conversation."""
        save_conversation_title("ghost", "orphan")
        assert conversation_exists("ghost") is False


@pytest.mark.unit
class TestConversationPinned:
    """Tests for the pinned flag on conversations."""

    def test_unpinned_by_default(self, _conv_dir: Path) -> None:
        """Conversations are not pinned unless flagged."""
        _seed_events_jsonl(_conv_dir, "conv-1", [{"role": "user", "content": "hi"}])
        assert list_conversations()[0].pinned is False

    def test_pinned_flag_round_trips_through_listing(self, _conv_dir: Path) -> None:
        """A saved pinned flag surfaces on the listing summary."""
        _seed_events_jsonl(_conv_dir, "conv-1", [{"role": "user", "content": "hi"}])
        save_conversation_pinned("conv-1", True)
        assert list_conversations()[0].pinned is True

    def test_pin_preserves_title(self, _conv_dir: Path) -> None:
        """Pinning merges into existing metadata rather than clobbering it."""
        _seed_events_jsonl(_conv_dir, "conv-1", [{"role": "user", "content": "hi"}])
        save_conversation_title("conv-1", "My Title")
        save_conversation_pinned("conv-1", True)

        meta = load_conversation_metadata("conv-1")
        assert meta["title"] == "My Title"
        assert meta["pinned"] is True

    def test_unpin_after_pin(self, _conv_dir: Path) -> None:
        """A conversation can be unpinned again."""
        _seed_events_jsonl(_conv_dir, "conv-1", [{"role": "user", "content": "hi"}])
        save_conversation_pinned("conv-1", True)
        save_conversation_pinned("conv-1", False)
        assert list_conversations()[0].pinned is False


@pytest.mark.unit
class TestConversationProfile:
    """Per-conversation agent profile persistence."""

    def test_no_profile_by_default(self, _conv_dir: Path) -> None:
        """A conversation without a saved profile returns None."""
        _seed_events_jsonl(_conv_dir, "conv-1", [{"role": "user", "content": "hi"}])
        assert load_conversation_profile("conv-1") is None

    def test_profile_round_trips(self, _conv_dir: Path) -> None:
        """A saved profile id loads back unchanged."""
        save_conversation_profile("conv-1", "research")
        assert load_conversation_profile("conv-1") == "research"

    def test_latest_profile_wins(self, _conv_dir: Path) -> None:
        """Switching profiles mid-conversation persists the newest pick."""
        save_conversation_profile("conv-1", "research")
        save_conversation_profile("conv-1", "creative")
        assert load_conversation_profile("conv-1") == "creative"

    def test_profile_preserves_other_metadata(self, _conv_dir: Path) -> None:
        """Saving a profile merges into existing metadata rather than clobbering it."""
        save_conversation_title("conv-1", "My Title")
        save_conversation_profile("conv-1", "research")

        meta = load_conversation_metadata("conv-1")
        assert meta["title"] == "My Title"
        assert meta["profile_id"] == "research"
