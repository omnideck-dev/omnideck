"""Tests for migration 016: grant the ``theme`` tool category to ``assistant``."""

import json

import pytest

from migrations._016_grant_theme_tools import migrate


def _write_assistant(state_dir, **fields):
    skills = state_dir / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    record = {"id": "assistant", "name": "assistant", "prompt": "hi", "tool_categories": ["memory"], **fields}
    (skills / "assistant.json").write_text(json.dumps(record), encoding="utf-8")


def _read_assistant(state_dir):
    return json.loads((state_dir / "skills" / "assistant.json").read_text(encoding="utf-8"))


@pytest.mark.unit
def test_appends_theme_to_assistant(tmp_path):
    _write_assistant(tmp_path, tool_categories=["memory", "email"])
    migrate(tmp_path)
    assert _read_assistant(tmp_path)["tool_categories"] == ["memory", "email", "theme"]


@pytest.mark.unit
def test_leaves_prompt_and_other_fields_alone(tmp_path):
    _write_assistant(tmp_path, prompt="my edited prompt", description="mine")
    migrate(tmp_path)
    record = _read_assistant(tmp_path)
    assert record["prompt"] == "my edited prompt"
    assert record["description"] == "mine"


@pytest.mark.unit
def test_already_granted_is_not_rewritten(tmp_path):
    _write_assistant(tmp_path, tool_categories=["theme", "memory"])
    path = tmp_path / "skills" / "assistant.json"
    before = path.read_text(encoding="utf-8")
    migrate(tmp_path)
    assert path.read_text(encoding="utf-8") == before


@pytest.mark.unit
def test_deleted_assistant_stays_deleted(tmp_path):
    (tmp_path / "skills").mkdir()
    migrate(tmp_path)
    assert not (tmp_path / "skills" / "assistant.json").exists()


@pytest.mark.unit
def test_no_skills_dir_is_noop(tmp_path):
    migrate(tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.unit
def test_corrupt_record_is_skipped(tmp_path):
    (tmp_path / "skills").mkdir()
    path = tmp_path / "skills" / "assistant.json"
    path.write_text("{not json", encoding="utf-8")
    migrate(tmp_path)
    assert path.read_text(encoding="utf-8") == "{not json"


@pytest.mark.unit
def test_shipped_assistant_default_grants_theme():
    """Fresh installs get theme from the shipped record, not the migration."""
    from pathlib import Path

    shipped = Path(__file__).parents[3] / "agent_core" / "skills" / "default_skills" / "assistant.json"
    assert "theme" in json.loads(shipped.read_text(encoding="utf-8"))["tool_categories"]
