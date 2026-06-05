"""Tests for migration 006: install default skills and grant ``assistant``.

The migration copies the shipped starter records into ``{state}/skills/`` (never
overwriting an existing file) and appends ``assistant`` to every existing
profile — regardless of which profiles exist or how they're configured.
"""

import json

import pytest

from migrations._006_install_default_skills import migrate

_STARTERS = {"assistant", "coder", "browser", "goal_planner", "image_generation", "music_generation", "desktop"}


def _write_profile(state_dir, pid, skills):
    d = state_dir / "agent_profiles"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{pid}.json").write_text(json.dumps({"id": pid, "name": pid.title(), "skills": skills}))


def _profile_skills(state_dir, pid):
    return json.loads((state_dir / "agent_profiles" / f"{pid}.json").read_text())["skills"]


def _installed_skill_ids(state_dir):
    return {p.stem for p in (state_dir / "skills").glob("*.json")}


@pytest.mark.unit
def test_installs_all_starter_records(tmp_path):
    migrate(tmp_path)
    assert _STARTERS <= _installed_skill_ids(tmp_path)


@pytest.mark.unit
def test_profile_with_skills_gets_assistant_appended(tmp_path):
    _write_profile(tmp_path, "research", skills=["browser"])
    migrate(tmp_path)
    assert _profile_skills(tmp_path, "research") == ["browser", "assistant"]


@pytest.mark.unit
def test_profile_with_no_skills_gets_assistant(tmp_path):
    _write_profile(tmp_path, "omnideck", skills=[])
    migrate(tmp_path)
    assert _profile_skills(tmp_path, "omnideck") == ["assistant"]


@pytest.mark.unit
def test_profile_already_granting_assistant_is_unchanged(tmp_path):
    _write_profile(tmp_path, "x", skills=["assistant", "coder"])
    migrate(tmp_path)
    assert _profile_skills(tmp_path, "x") == ["assistant", "coder"]


@pytest.mark.unit
def test_idempotent(tmp_path):
    _write_profile(tmp_path, "research", skills=["browser"])
    migrate(tmp_path)
    migrate(tmp_path)
    assert _profile_skills(tmp_path, "research") == ["browser", "assistant"]


@pytest.mark.unit
def test_runs_with_no_profiles(tmp_path):
    migrate(tmp_path)  # no agent_profiles dir — must not error
    assert (tmp_path / "skills" / "assistant.json").exists()


@pytest.mark.unit
def test_existing_skill_file_not_overwritten(tmp_path):
    d = tmp_path / "skills"
    d.mkdir(parents=True)
    (d / "coder.json").write_text(json.dumps({"id": "coder", "name": "My Coder", "tool_categories": []}))
    migrate(tmp_path)
    assert json.loads((d / "coder.json").read_text())["name"] == "My Coder"
