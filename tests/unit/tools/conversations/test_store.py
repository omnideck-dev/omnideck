"""Unit tests for conversation persistence store."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from conversations._store import (
    delete_conversation,
    list_conversations,
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
        # Override "old" conv's timestamp to be earlier.
        old_path = _conv_dir / "old" / "events.jsonl"
        old_path.write_text(old_path.read_text().replace(
            "2026-01-01T00:00:01", "2025-01-01T00:00:01",
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
