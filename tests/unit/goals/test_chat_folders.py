"""Goals saved inside their chat's folder, and chat delete, archive and restore."""

import logging
import shutil
from pathlib import Path

import pytest

from goals import GoalNotFoundError, GoalStore

from tests.unit.goals.support import claim_wake, create


@pytest.fixture
def store(tmp_path):
    return GoalStore(tmp_path)


def archive(store: GoalStore, conversation_id: str) -> bool:
    destination = store._base / "_archived" / conversation_id
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(store._base / conversation_id, destination)
    return True


def unarchive(store: GoalStore, conversation_id: str) -> bool:
    shutil.move(store._base / "_archived" / conversation_id, store._base / conversation_id)
    return True


def break_goal_file(store: GoalStore, conversation_id: str, goal_id: str) -> Path:
    path = store._base / conversation_id / "goals" / goal_id / "goal.json"
    path.write_text(path.read_text()[:40])
    return path


def test_goal_is_saved_in_its_chat_folder(store):
    goal = create(store)
    folder = store._base / "chat" / "goals" / goal.id
    assert (folder / "goal.json").is_file()
    assert [path.name for path in (folder / "history").iterdir()] == ["000000000001.json"]


def test_chat_goals_read_opens_only_that_chat_folder(store, monkeypatch):
    goal = create(store)
    create(store, "other")
    reads: list[Path] = []
    original = Path.read_text

    def counted(path, *args, **kwargs):
        reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted)
    assert [item.id for item in store.history("chat")] == [goal.id]
    assert all(path.parts[len(store._base.parts)] == "chat" for path in reads)


def test_list_reads_active_and_archived_chats(store):
    kept = create(store)
    archived = create(store, "old")
    store.archive_conversation("old", lambda: archive(store, "old"))
    assert {goal.id for goal in store.list()} == {kept.id, archived.id}


def test_archive_drops_chat_goals_from_memory(store):
    goal = create(store)
    store.archive_conversation("chat", lambda: archive(store, "chat"))
    assert store.get(goal.id) is None
    assert store.current("chat") is None
    assert store.due() == []
    assert store.latest_goals() == []
    assert not (store._base / "chat").exists()
    assert GoalStore(store._base).due() == []


def test_unarchive_adds_chat_goals_back_paused(store):
    goal = create(store)
    store.archive_conversation("chat", lambda: archive(store, "chat"))
    store.unarchive_conversation("chat", lambda: unarchive(store, "chat"))
    restored = store.current("chat")
    assert restored is not None and restored.id == goal.id and restored.paused
    assert store.due() == []
    assert [item.id for item in store.latest_goals()] == [goal.id]


def test_save_after_archive_raises_not_found_and_creates_no_folder(store):
    goal = create(store)
    store.archive_conversation("chat", lambda: archive(store, "chat"))
    with pytest.raises(GoalNotFoundError):
        store.update(goal.id, goal.revision + 1, summary="Late work")
    assert not (store._base / "chat").exists()


def test_save_after_delete_raises_not_found(store):
    goal = create(store)
    store.delete_conversation("chat", lambda: shutil.rmtree(store._base / "chat") is None)
    with pytest.raises(GoalNotFoundError):
        store.pause(goal.id)
    assert not (store._base / "chat").exists()


def test_archive_while_a_run_ends_leaves_one_copy(store):
    goal = claim_wake(store, create(store))
    store.archive_conversation("chat", lambda: archive(store, "chat"))
    assert store.finish_run(goal.id, "claim", "run-1", "success") is None
    assert not (store._base / "chat").exists()
    assert [path.parent.name for path in store._base.glob("*/*/goals/*/goal.json")] == [goal.id]


def test_list_skips_unreadable_goal_file(store, caplog):
    good = create(store)
    broken = create(store, "broken")
    path = break_goal_file(store, "broken", broken.id)
    with caplog.at_level(logging.ERROR):
        assert [goal.id for goal in store.list()] == [good.id]
    assert str(path) in caplog.text


def test_load_keeps_good_goals_when_one_file_is_broken(store, caplog):
    good = create(store)
    broken = create(store, "broken")
    path = break_goal_file(store, "broken", broken.id)
    fresh = GoalStore(store._base)
    with caplog.at_level(logging.ERROR):
        fresh.load()
    assert [goal.id for goal in fresh.due()] == [good.id]
    assert fresh.current("chat").id == good.id
    assert str(path) in caplog.text


def test_chat_goals_read_skips_unreadable_goal_file(store, caplog):
    first = create(store)
    store.cancel(first.id)
    second = create(store)
    path = break_goal_file(store, "chat", second.id)
    with caplog.at_level(logging.ERROR):
        assert [goal.id for goal in store.history("chat")] == [first.id]
    assert store.latest("chat").id == first.id
    assert str(path) in caplog.text
