"""A broken goal file never stops a chat: other chats read none, and its own chat replies without goal tools."""

import logging
from pathlib import Path

from ._support import reply

GOAL_TOOLS = {"read_goal", "read_goal_history", "update_goal", "update_goal_questions", "choose_next_action"}


def break_goal(tmp_path: Path, conversation_id: str, goal_id: str) -> Path:
    path = tmp_path / "conversations" / conversation_id / "goals" / goal_id / "goal.json"
    path.write_text("{")
    return path


async def test_chat_without_a_goal_replies_with_a_broken_goal_file_in_another_chat(harness, tmp_path, monkeypatch):
    h = harness
    h.profile()
    other = h.goal("other", "A goal whose file breaks")
    break_goal(tmp_path, "other", other.id)
    reads: list[Path] = []
    original = Path.read_text

    def counted(path, *args, **kwargs):
        reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted)
    h.provider.plan("leaf", reply("Hello there"))
    events = await h.run(conversation="plain")
    assert any(event.payload.type == "turn_end" for event in events)
    assert not [path for path in reads if "goals" in path.parts and "other" in path.parts]


async def test_chat_with_a_broken_newest_goal_file_replies_without_goal_tools(harness, tmp_path, caplog):
    h = harness
    h.profile()
    goal = h.goal("broken", "A goal whose file breaks")
    path = break_goal(tmp_path, "broken", goal.id)
    h.provider.plan("leaf", reply("Hello there"))
    with caplog.at_level(logging.ERROR):
        await h.run(conversation="broken")
    assert not GOAL_TOOLS & set(h.provider.requests[-1]["tools"])
    assert str(path) in caplog.text
