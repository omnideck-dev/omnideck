"""Unit tests for ``server.message_handler`` cache + persistence behavior."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sdk.context import ConversationHistory
from server import message_handler as mh


def _seed_events_jsonl(conv_dir: Path, conv_id: str, user_content: str = "hi") -> None:
    """Write a minimal events.jsonl so _get_conversation treats the
    conversation as not-new."""
    import json
    d = conv_dir / conv_id
    d.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({
            "id": f"evt_{conv_id}_s", "type": "agent_started",
            "timestamp": "2026-01-01T00:00:00",
            "conversation_id": conv_id, "agent_id": "root.test.1",
            "agent_name": "TEST", "parent_agent_id": None,
        }),
        json.dumps({
            "id": f"evt_{conv_id}_u", "type": "user_message",
            "timestamp": "2026-01-01T00:00:01",
            "conversation_id": conv_id, "agent_id": "root.test.1",
            "content": user_content, "attachments": [],
        }),
    ]
    (d / "events.jsonl").write_text("\n".join(lines) + "\n")


@pytest.fixture(autouse=True)
async def _clear_in_memory_conversations() -> AsyncIterator[None]:
    """Reset the module-global conversation cache between tests."""
    mh._conversations.clear()
    yield
    mh._conversations.clear()


@pytest.fixture(autouse=True)
def _stub_browser_release():
    """Stub out release_agent_browser so eviction doesn't touch Playwright."""
    with patch.object(mh, "release_agent_browser", new_callable=AsyncMock):
        yield


async def test_get_conversation_cold_cache_no_disk_creates_empty_and_marks_new() -> None:
    """No in-memory entry, no on-disk history -> empty + is_new=True."""
    conv, is_new = await mh._get_conversation("brand-new-id")
    assert len(conv) == 0
    assert conv.instance_id == "brand-new-id"
    assert is_new is True


async def test_get_conversation_cold_cache_with_events_marks_not_new(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """An existing events.jsonl on disk flips the is_new flag."""
    monkeypatch.setattr(
        "conversations._store._get_conversations_dir", lambda: tmp_path,
    )
    _seed_events_jsonl(tmp_path, "existing")

    _conv, is_new = await mh._get_conversation("existing")
    assert is_new is False


async def test_get_conversation_warm_cache_returns_in_memory_instance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """An in-memory entry is returned as-is — no re-read from disk."""
    monkeypatch.setattr(
        "conversations._store._get_conversations_dir", lambda: tmp_path,
    )
    cached = ConversationHistory(instance_id="cid", conversation_id="cid")
    mh._conversations["cid"] = cached
    _seed_events_jsonl(tmp_path, "cid", user_content="from-disk")

    conv, is_new = await mh._get_conversation("cid")

    assert conv is cached
    assert is_new is False


async def test_get_conversation_subsequent_call_returns_same_instance() -> None:
    """Two calls for the same id return the same ConversationHistory object."""
    first, first_new = await mh._get_conversation("same-id")
    second, second_new = await mh._get_conversation("same-id")
    assert first is second
    assert first_new is True
    assert second_new is False


async def test_get_conversation_empty_id_raises() -> None:
    """Empty string is rejected."""
    with pytest.raises(ValueError, match="conversation_id is required"):
        await mh._get_conversation("")


async def test_get_conversation_corrupted_history_falls_back_to_empty(tmp_path: Path) -> None:
    """A malformed history.json is treated as no on-disk history."""
    from conversations._store import _get_conversations_dir

    cid = "corrupted"
    conv_dir = _get_conversations_dir() / cid
    conv_dir.mkdir(parents=True)
    (conv_dir / "history.json").write_text("{not valid json", encoding="utf-8")

    conv, is_new = await mh._get_conversation(cid)

    assert len(conv) == 0
    assert is_new is True


async def test_lru_evicts_oldest_when_cap_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inserting beyond the cap evicts the least-recently-used entry."""
    monkeypatch.setattr(mh, "_MAX_CACHED_CONVERSATIONS", 3)

    await mh._get_conversation("a")
    await mh._get_conversation("b")
    await mh._get_conversation("c")
    assert list(mh._conversations) == ["a", "b", "c"]

    await mh._get_conversation("d")

    assert "a" not in mh._conversations
    assert list(mh._conversations) == ["b", "c", "d"]


async def test_lru_access_promotes_to_most_recently_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cache hit moves the entry to the end so it survives the next eviction."""
    monkeypatch.setattr(mh, "_MAX_CACHED_CONVERSATIONS", 3)

    await mh._get_conversation("a")
    await mh._get_conversation("b")
    await mh._get_conversation("c")

    # Touch 'a' — should become most-recently-used.
    await mh._get_conversation("a")
    assert list(mh._conversations) == ["b", "c", "a"]

    # Inserting a fourth should now evict 'b', not 'a'.
    await mh._get_conversation("d")
    assert "b" not in mh._conversations
    assert "a" in mh._conversations


async def test_lru_skips_active_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Conversations whose turn is in flight are not evicted."""
    monkeypatch.setattr(mh, "_MAX_CACHED_CONVERSATIONS", 2)
    monkeypatch.setattr(mh, "is_turn_active", lambda cid: cid == "a")

    await mh._get_conversation("a")
    await mh._get_conversation("b")
    assert list(mh._conversations) == ["a", "b"]

    # Inserting 'c' would normally evict 'a' (oldest). Pinning skips
    # over 'a' and evicts 'b' instead.
    await mh._get_conversation("c")
    assert "a" in mh._conversations
    assert "b" not in mh._conversations
    assert "c" in mh._conversations


async def test_lru_overflow_when_all_active(monkeypatch: pytest.MonkeyPatch) -> None:
    """When every cached conv is mid-turn, the cache temporarily overflows."""
    monkeypatch.setattr(mh, "_MAX_CACHED_CONVERSATIONS", 2)
    monkeypatch.setattr(mh, "is_turn_active", lambda _cid: True)

    await mh._get_conversation("a")
    await mh._get_conversation("b")
    await mh._get_conversation("c")

    assert len(mh._conversations) == 3
    assert set(mh._conversations) == {"a", "b", "c"}


async def test_lru_does_not_evict_just_inserted_when_others_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Just-inserted conv survives even when every existing entry is mid-turn."""
    monkeypatch.setattr(mh, "_MAX_CACHED_CONVERSATIONS", 2)
    monkeypatch.setattr(mh, "is_turn_active", lambda cid: cid in {"a", "b"})

    await mh._get_conversation("a")
    await mh._get_conversation("b")
    await mh._get_conversation("c")

    assert "c" in mh._conversations
    assert set(mh._conversations) == {"a", "b", "c"}


async def test_resume_conversation_marks_most_recently_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """resume_conversation places the resumed entry at the LRU tail."""
    monkeypatch.setattr(
        "conversations._store._get_conversations_dir", lambda: tmp_path,
    )

    await mh._get_conversation("a")

    conv_dir = tmp_path / "from-disk"
    conv_dir.mkdir(parents=True, exist_ok=True)
    (conv_dir / "events.jsonl").write_text(
        '{"id":"evt_s","type":"agent_started","timestamp":"2026-01-01T00:00:00",'
        '"conversation_id":"from-disk","agent_id":"root.a.1","agent_name":"A",'
        '"parent_agent_id":null}\n'
        '{"id":"evt_u","type":"user_message","timestamp":"2026-01-01T00:00:01",'
        '"conversation_id":"from-disk","agent_id":"root.a.1","content":"hi",'
        '"attachments":[]}\n'
    )

    result = await mh.resume_conversation("from-disk")
    assert result is not None
    assert list(mh._conversations)[-1] == "from-disk"


async def test_resume_includes_spawn_requested_in_ui_events(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The resume API filters events.jsonl down to a UI-replay subset.
    spawn_requested has to be in that subset, otherwise the frontend
    can't render the spawn card on a resumed conversation."""
    monkeypatch.setattr(
        "conversations._store._get_conversations_dir", lambda: tmp_path,
    )
    conv_dir = tmp_path / "spawn-conv"
    conv_dir.mkdir(parents=True, exist_ok=True)
    (conv_dir / "events.jsonl").write_text(
        '{"id":"evt_s","type":"agent_started","timestamp":"2026-01-01T00:00:00+00:00",'
        '"conversation_id":"spawn-conv","agent_id":"root.a.1","agent_name":"A",'
        '"parent_agent_id":null}\n'
        '{"id":"evt_u","type":"user_message","timestamp":"2026-01-01T00:00:01+00:00",'
        '"conversation_id":"spawn-conv","agent_id":"root.a.1","content":"go",'
        '"attachments":[]}\n'
        '{"id":"evt_sr","type":"spawn_requested","timestamp":"2026-01-01T00:00:02+00:00",'
        '"conversation_id":"spawn-conv","agent_id":"root.a.1","correlation_id":"c1"}\n'
        '{"id":"evt_cu","type":"context_usage","timestamp":"2026-01-01T00:00:03+00:00",'
        '"conversation_id":"spawn-conv","agent_id":"root.a.1","context_used":100}\n'
    )
    result = await mh.resume_conversation("spawn-conv")
    assert result is not None
    types = [e["type"] for e in result["events"]]
    assert "spawn_requested" in types
    # context_usage is consumed by the live context meter only; it
    # shouldn't be replayed (and would create noise on resume).
    assert "context_usage" not in types


def test_augment_message_with_attachments_returns_text_and_structured_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The augment helper returns both the LLM-facing text and the structured
    attachments needed to populate a UserMessagePayload."""
    from agents.types import Data

    paths = iter(["/virt/uploads/a.png", "/virt/uploads/b.csv"])
    monkeypatch.setattr(mh, "receive_attachment", lambda **_: next(paths))

    data = [
        Data(base64_encoded="aaaa", content_type="image/png", filename="a.png"),
        Data(base64_encoded="bbbb", content_type="text/csv", filename="b.csv"),
    ]
    text, attachments = mh._augment_message_with_attachments("describe these", data)

    assert "describe these" in text
    assert "/virt/uploads/a.png" in text
    assert "/virt/uploads/b.csv" in text

    assert len(attachments) == 2
    a, b = attachments
    assert (a.filename, a.content_type, a.path) == ("a.png", "image/png", "/virt/uploads/a.png")
    assert (b.filename, b.content_type, b.path) == ("b.csv", "text/csv", "/virt/uploads/b.csv")


def test_augment_message_with_attachments_falls_back_to_unnamed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When an attachment has no filename, the attachment record still gets a name."""
    from agents.types import Data

    monkeypatch.setattr(mh, "receive_attachment", lambda **_: "/virt/uploads/synth.png")

    data = [Data(base64_encoded="aaaa", content_type="image/png", filename=None)]
    _text, attachments = mh._augment_message_with_attachments("look", data)

    assert len(attachments) == 1
    assert attachments[0].filename == "unnamed"
    assert attachments[0].path == "/virt/uploads/synth.png"
