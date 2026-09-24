"""Tests for migration 013 — rename the Goals feature to Routines in state."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from migrations._013_goals_to_routines import migrate

pytestmark = pytest.mark.unit

_OLD_CONV = "goals/g1/run1/tr1"
_NEW_CONV = "routines/g1/run1/tr1"


def _artifact_id(conversation_id: str, path: str) -> str:
    return hashlib.sha256(f"{conversation_id}\x00{path}".encode("utf-8")).hexdigest()


def _seed_store(state: Path) -> None:
    """Write one routine file and one run file under the legacy goals/ store."""
    (state / "goals").mkdir(parents=True)
    (state / "goals" / "g1.json").write_text(
        json.dumps(
            {
                "id": "g1",
                "description": "daily digest",
                "status": "active",
                "created_at": "2026-01-01",
                "tasks": [
                    {"id": "task1", "goal_id": "g1", "description": "d", "instruction": "i"}
                ],
            }
        ),
        encoding="utf-8",
    )
    runs = state / "goals" / "g1" / "runs"
    runs.mkdir(parents=True)
    (runs / "run1.json").write_text(
        json.dumps(
            {
                "id": "run1",
                "goal_id": "g1",
                "run_number": 1,
                "status": "completed",
                "task_results": [
                    {
                        "id": "tr1",
                        "run_id": "run1",
                        "task_id": "task1",
                        "status": "completed",
                        "conversation_id": _OLD_CONV,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_moves_store_and_renames_goal_id(tmp_path: Path) -> None:
    _seed_store(tmp_path)

    migrate(tmp_path)

    assert not (tmp_path / "goals").exists()
    routine = json.loads((tmp_path / "routines" / "g1.json").read_text(encoding="utf-8"))
    assert routine["tasks"][0]["routine_id"] == "g1"
    assert "goal_id" not in routine["tasks"][0]

    run = json.loads(
        (tmp_path / "routines" / "g1" / "runs" / "run1.json").read_text(encoding="utf-8")
    )
    assert run["routine_id"] == "g1"
    assert "goal_id" not in run
    assert run["task_results"][0]["conversation_id"] == _NEW_CONV


def test_moves_run_conversations_and_reprefixes_event_ids(tmp_path: Path) -> None:
    conv = tmp_path / "conversations" / "goals" / "g1" / "run1" / "tr1"
    conv.mkdir(parents=True)
    (conv / "events.jsonl").write_text(
        json.dumps({"type": "text", "conversation_id": _OLD_CONV, "data": "hi"}) + "\n",
        encoding="utf-8",
    )

    migrate(tmp_path)

    assert not (tmp_path / "conversations" / "goals").exists()
    moved = tmp_path / "conversations" / "routines" / "g1" / "run1" / "tr1" / "events.jsonl"
    event = json.loads(moved.read_text(encoding="utf-8").strip())
    assert event["conversation_id"] == _NEW_CONV


def test_rekeys_goal_run_artifacts(tmp_path: Path) -> None:
    path = "/home/omnideck/out.txt"
    old_id = _artifact_id(_OLD_CONV, path)
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "artifacts": {
                    old_id: {
                        "id": old_id,
                        "conversation_id": _OLD_CONV,
                        "path": path,
                        "filename": "out.txt",
                        "content_type": "text/plain",
                        "created_at": "a",
                        "updated_at": "b",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    migrate(tmp_path)

    index = json.loads((tmp_path / "artifacts" / "index.json").read_text(encoding="utf-8"))
    new_id = _artifact_id(_NEW_CONV, path)
    assert old_id not in index["artifacts"]
    entry = index["artifacts"][new_id]
    assert entry["id"] == new_id
    assert entry["conversation_id"] == _NEW_CONV


def test_renames_skill_and_rewrites_references(tmp_path: Path) -> None:
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "goal_planner.json").write_text(
        json.dumps(
            {
                "id": "goal_planner",
                "name": "goal_planner",
                "description": "manage autonomous goals",
                "prompt": "Use begin_goal, commit_goal, list_goals, trigger_goal.",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "agent_profiles").mkdir()
    (tmp_path / "agent_profiles" / "omnideck.json").write_text(
        json.dumps(
            {
                "id": "omnideck",
                "system_prompt": "load goal_planner. WHY - the goal and how it fits.",
                "skills": ["goal_planner", "coder"],
            }
        ),
        encoding="utf-8",
    )

    migrate(tmp_path)

    assert not (tmp_path / "skills" / "goal_planner.json").exists()
    skill = json.loads((tmp_path / "skills" / "routine_planner.json").read_text(encoding="utf-8"))
    assert skill["id"] == "routine_planner"
    assert "goal" not in skill["prompt"].lower()
    assert "begin_routine" in skill["prompt"]

    profile = json.loads(
        (tmp_path / "agent_profiles" / "omnideck.json").read_text(encoding="utf-8")
    )
    assert profile["skills"] == ["routine_planner", "coder"]
    assert "routine_planner" in profile["system_prompt"]
    # The ordinary English word "goal" in prose stays untouched.
    assert "the goal and how it fits" in profile["system_prompt"]


def test_preserves_english_goal_in_conversation_titles(tmp_path: Path) -> None:
    conv = tmp_path / "conversations" / "abc-123"
    conv.mkdir(parents=True)
    (conv / "metadata.json").write_text(
        json.dumps({"title": "reach my goals", "loaded_skills": ["goal_planner"]}),
        encoding="utf-8",
    )

    migrate(tmp_path)

    meta = json.loads((conv / "metadata.json").read_text(encoding="utf-8"))
    assert meta["title"] == "reach my goals"
    assert meta["loaded_skills"] == ["routine_planner"]


def test_noop_on_fresh_install(tmp_path: Path) -> None:
    migrate(tmp_path)

    assert not (tmp_path / "routines").exists()
    assert not (tmp_path / "conversations").exists()


def test_second_run_is_stable(tmp_path: Path) -> None:
    _seed_store(tmp_path)

    migrate(tmp_path)
    after_first = (tmp_path / "routines" / "g1" / "runs" / "run1.json").read_text(encoding="utf-8")
    migrate(tmp_path)
    after_second = (tmp_path / "routines" / "g1" / "runs" / "run1.json").read_text(encoding="utf-8")

    assert after_first == after_second
