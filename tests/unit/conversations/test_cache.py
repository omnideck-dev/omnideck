"""Unit tests for the conversation cache and resume-state loader."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from conversations import _cache as cc
from conversations._store import save_conversation_profile
from sdk.context import ConversationHistory


def _seed_events_jsonl(conv_dir: Path, conv_id: str, user_content: str = "hi") -> None:
    """Write a minimal persisted event log."""
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
    cc._conversations.clear()
    yield
    cc._conversations.clear()


@pytest.fixture(autouse=True)
def _stub_conversation_exit_hooks():
    """Stub the eviction hook so it doesn't touch Playwright or other resources."""
    with patch.object(cc, "run_conversation_exit_hooks", new_callable=AsyncMock):
        yield


async def test_get_conversation_cold_cache_no_disk_creates_empty() -> None:
    """No in-memory entry or on-disk history creates an empty history."""
    conv = await cc.get_or_create_conversation("brand-new-id")
    assert len(conv) == 0


async def test_get_conversation_cold_cache_hydrates_events(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """An existing events.jsonl is loaded on a cold cache."""
    monkeypatch.setattr(
        "conversations._store._get_conversations_dir", lambda: tmp_path,
    )
    _seed_events_jsonl(tmp_path, "existing")

    conv = await cc.get_or_create_conversation("existing")
    assert [event["type"] for event in conv.recorded_events] == [
        "agent_started",
        "user_message",
    ]


async def test_get_conversation_warm_cache_returns_in_memory_instance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """An in-memory entry is returned as-is — no re-read from disk."""
    monkeypatch.setattr(
        "conversations._store._get_conversations_dir", lambda: tmp_path,
    )
    cached = ConversationHistory(conversation_id="cid")
    cc._conversations["cid"] = cached
    _seed_events_jsonl(tmp_path, "cid", user_content="from-disk")

    conv = await cc.get_or_create_conversation("cid")

    assert conv is cached


async def test_get_conversation_subsequent_call_returns_same_instance() -> None:
    """Two calls for the same id return the same ConversationHistory object."""
    first = await cc.get_or_create_conversation("same-id")
    second = await cc.get_or_create_conversation("same-id")
    assert first is second


async def test_get_conversation_empty_id_raises() -> None:
    """Empty string is rejected."""
    with pytest.raises(ValueError, match="conversation_id is required"):
        await cc.get_or_create_conversation("")


async def test_get_conversation_corrupted_history_falls_back_to_empty(tmp_path: Path) -> None:
    """A malformed history.json is treated as no on-disk history."""
    from conversations._store import _get_conversations_dir

    cid = "corrupted"
    conv_dir = _get_conversations_dir() / cid
    conv_dir.mkdir(parents=True)
    (conv_dir / "history.json").write_text("{not valid json", encoding="utf-8")

    conv = await cc.get_or_create_conversation(cid)

    assert len(conv) == 0


async def test_lru_evicts_oldest_when_cap_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inserting beyond the cap evicts the least-recently-used entry."""
    monkeypatch.setattr(cc, "_MAX_CACHED_CONVERSATIONS", 3)

    await cc.get_or_create_conversation("a")
    await cc.get_or_create_conversation("b")
    await cc.get_or_create_conversation("c")
    assert list(cc._conversations) == ["a", "b", "c"]

    await cc.get_or_create_conversation("d")

    assert "a" not in cc._conversations
    assert list(cc._conversations) == ["b", "c", "d"]


async def test_lru_access_promotes_to_most_recently_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cache hit moves the entry to the end so it survives the next eviction."""
    monkeypatch.setattr(cc, "_MAX_CACHED_CONVERSATIONS", 3)

    await cc.get_or_create_conversation("a")
    await cc.get_or_create_conversation("b")
    await cc.get_or_create_conversation("c")

    # Touch 'a' — should become most-recently-used.
    await cc.get_or_create_conversation("a")
    assert list(cc._conversations) == ["b", "c", "a"]

    # Inserting a fourth should now evict 'b', not 'a'.
    await cc.get_or_create_conversation("d")
    assert "b" not in cc._conversations
    assert "a" in cc._conversations


async def test_lru_skips_active_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Conversations whose turn is in flight are not evicted."""
    monkeypatch.setattr(cc, "_MAX_CACHED_CONVERSATIONS", 2)
    monkeypatch.setattr(cc, "is_turn_active", lambda cid: cid == "a")

    await cc.get_or_create_conversation("a")
    await cc.get_or_create_conversation("b")
    assert list(cc._conversations) == ["a", "b"]

    # Inserting 'c' would normally evict 'a' (oldest). Pinning skips
    # over 'a' and evicts 'b' instead.
    await cc.get_or_create_conversation("c")
    assert "a" in cc._conversations
    assert "b" not in cc._conversations
    assert "c" in cc._conversations


async def test_lru_overflow_when_all_active(monkeypatch: pytest.MonkeyPatch) -> None:
    """When every cached conv is mid-turn, the cache temporarily overflows."""
    monkeypatch.setattr(cc, "_MAX_CACHED_CONVERSATIONS", 2)
    monkeypatch.setattr(cc, "is_turn_active", lambda _cid: True)

    await cc.get_or_create_conversation("a")
    await cc.get_or_create_conversation("b")
    await cc.get_or_create_conversation("c")

    assert len(cc._conversations) == 3
    assert set(cc._conversations) == {"a", "b", "c"}


async def test_lru_does_not_evict_just_inserted_when_others_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Just-inserted conv survives even when every existing entry is mid-turn."""
    monkeypatch.setattr(cc, "_MAX_CACHED_CONVERSATIONS", 2)
    monkeypatch.setattr(cc, "is_turn_active", lambda cid: cid in {"a", "b"})

    await cc.get_or_create_conversation("a")
    await cc.get_or_create_conversation("b")
    await cc.get_or_create_conversation("c")

    assert "c" in cc._conversations
    assert set(cc._conversations) == {"a", "b", "c"}


async def test_load_resume_state_marks_conversation_most_recently_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Loading resume state places the conversation at the LRU tail."""
    monkeypatch.setattr(
        "conversations._store._get_conversations_dir", lambda: tmp_path,
    )

    await cc.get_or_create_conversation("a")

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

    result = await cc.load_conversation_resume_state("from-disk")
    assert result is not None
    assert list(cc._conversations)[-1] == "from-disk"


async def test_resume_returns_empty_snapshot_without_persisted_events() -> None:
    """Loading before the first event returns the normal snapshot shape."""
    result = await cc.load_conversation_resume_state("just-reserved")

    assert result.messages == []
    assert result.events == []
    assert "just-reserved" in cc._conversations


async def test_resume_returns_complete_persisted_event_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Resume returns persisted records without a second UI allowlist."""
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
    result = await cc.load_conversation_resume_state("spawn-conv")
    assert result is not None
    types = [e["type"] for e in result.events]
    assert "spawn_requested" in types
    assert "context_usage" in types


async def test_load_resume_state_returns_saved_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Resume state surfaces the conversation's locked-in agent profile."""
    monkeypatch.setattr("conversations._store._get_conversations_dir", lambda: tmp_path)
    _seed_events_jsonl(tmp_path, "c-prof")
    save_conversation_profile("c-prof", "research")

    result = await cc.load_conversation_resume_state("c-prof")

    assert result is not None
    assert result.profile_id == "research"


async def test_load_resume_state_profile_none_when_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A conversation with no saved profile resumes with None."""
    monkeypatch.setattr("conversations._store._get_conversations_dir", lambda: tmp_path)
    _seed_events_jsonl(tmp_path, "c-old")

    result = await cc.load_conversation_resume_state("c-old")

    assert result is not None
    assert result.profile_id is None


async def test_resume_returns_browser_tabs_sidecar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Resume carries the latest-per-tab snapshots from browser_tabs.json.

    Screenshots are not in the event log.
    """
    import json
    monkeypatch.setattr("conversations._store._get_conversations_dir", lambda: tmp_path)
    _seed_events_jsonl(tmp_path, "c-tabs")
    (tmp_path / "c-tabs" / "browser_tabs.json").write_text(json.dumps({
        "1": {"tab_id": "1", "url": "https://a.example", "title": "A",
              "screenshot": "png==", "agent_id": "root.test.1",
              "timestamp": "2026-01-01T00:00:05+00:00"},
    }), encoding="utf-8")

    result = await cc.load_conversation_resume_state("c-tabs")

    assert result is not None
    (tab,) = result.browser_tabs
    assert tab["url"] == "https://a.example"
    assert tab["agent_id"] == "root.test.1"


async def test_resume_returns_terminal_sidecar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Resume carries the per-agent terminal transcripts from terminal.json."""
    import json
    monkeypatch.setattr("conversations._store._get_conversations_dir", lambda: tmp_path)
    _seed_events_jsonl(tmp_path, "c-term")
    (tmp_path / "c-term" / "terminal.json").write_text(json.dumps({
        "root.test.1": [{"cmd_id": "c-1", "cmd": "ls", "status": "completed",
                         "stdout": "a.txt\n", "stderr": None, "exit_code": 0,
                         "agent_id": "root.test.1",
                         "timestamp": "2026-01-01T00:00:05+00:00"}],
    }), encoding="utf-8")

    result = await cc.load_conversation_resume_state("c-term")

    assert result is not None
    (entry,) = result.terminal["root.test.1"]
    assert entry["cmd"] == "ls"
    assert entry["stdout"] == "a.txt\n"


async def test_warm_resume_reads_complete_log_from_disk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A warm cache cannot narrow the durable resume payload."""
    monkeypatch.setattr("conversations._store._get_conversations_dir", lambda: tmp_path)
    _seed_events_jsonl(tmp_path, "c-warm")
    path = tmp_path / "c-warm" / "events.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            '{"id":"evt_context","type":"context_usage",'
            '"timestamp":"2026-01-01T00:00:03+00:00",'
            '"conversation_id":"c-warm","agent_id":"root.test.1",'
            '"context_used":100,"context_limit":1000,"fill_ratio":0.1,'
            '"compaction_threshold":0.75,"iteration":1,"max_iterations":10}\n',
        )

    await cc.get_or_create_conversation("c-warm")
    cc._conversations["c-warm"].seed_events([])

    result = await cc.load_conversation_resume_state("c-warm")

    assert result is not None
    assert [event["type"] for event in result.events] == [
        "agent_started", "user_message", "context_usage",
    ]
