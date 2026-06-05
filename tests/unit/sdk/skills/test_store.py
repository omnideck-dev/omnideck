"""Tests for the skill record store.

A SkillRecord is the persisted form of a skill: prompt text plus the tool category
ids it grants, keyed by a stable id with a unique display name. These cover the
JSON round-trip, CRUD by id, name-uniqueness on save, and tolerating bad files.
"""

import json

import pytest

from sdk.skills._store import (
    SkillRecord,
    delete_skill_record,
    get_skill_record,
    list_skill_records,
    save_skill_record,
)


@pytest.fixture(autouse=True)
def _isolate_skills(tmp_path, monkeypatch):
    """Point the store at a temp directory per test."""
    monkeypatch.setattr("sdk.skills._store._skills_dir", lambda: tmp_path / "skills")


def _record(**overrides) -> SkillRecord:
    defaults = {"id": "coder", "name": "Coder", "prompt": "Write code.", "tool_categories": ["coding"]}
    defaults.update(overrides)
    return SkillRecord(**defaults)


@pytest.mark.unit
def test_minimal_record_defaults():
    r = SkillRecord(id="x", name="X")
    assert r.tool_categories == []
    assert r.enabled is True


@pytest.mark.unit
def test_record_roundtrip_serialization():
    r = _record(tool_categories=["coding", "memory"], description="d")
    r2 = SkillRecord.model_validate(json.loads(json.dumps(r.model_dump())))
    assert r2 == r


@pytest.mark.unit
def test_save_and_get():
    save_skill_record(_record())
    loaded = get_skill_record("coder")
    assert loaded is not None
    assert loaded.name == "Coder"
    assert loaded.tool_categories == ["coding"]


@pytest.mark.unit
def test_get_nonexistent_returns_none():
    assert get_skill_record("nope") is None


@pytest.mark.unit
def test_list_empty():
    assert list_skill_records() == []


@pytest.mark.unit
def test_list_sorted_by_name():
    save_skill_record(_record(id="z", name="Zebra"))
    save_skill_record(_record(id="a", name="Alpha"))
    assert [r.name for r in list_skill_records()] == ["Alpha", "Zebra"]


@pytest.mark.unit
def test_delete():
    save_skill_record(_record())
    assert delete_skill_record("coder") is True
    assert get_skill_record("coder") is None


@pytest.mark.unit
def test_delete_nonexistent_returns_false():
    assert delete_skill_record("nope") is False


@pytest.mark.unit
def test_save_overwrites_same_id():
    save_skill_record(_record(prompt="v1"))
    save_skill_record(_record(prompt="v2"))
    assert get_skill_record("coder").prompt == "v2"


@pytest.mark.unit
def test_stored_one_file_per_id(tmp_path):
    save_skill_record(_record())
    assert (tmp_path / "skills" / "coder.json").is_file()


@pytest.mark.unit
def test_duplicate_name_under_different_id_rejected():
    save_skill_record(_record(id="coder", name="Coder"))
    with pytest.raises(ValueError, match="name"):
        save_skill_record(_record(id="other", name="Coder"))


@pytest.mark.unit
def test_rename_same_id_is_allowed():
    save_skill_record(_record(id="coder", name="Coder"))
    save_skill_record(_record(id="coder", name="Coder 2"))
    assert get_skill_record("coder").name == "Coder 2"


@pytest.mark.unit
def test_broken_file_is_skipped(tmp_path):
    d = tmp_path / "skills"
    d.mkdir(parents=True)
    (d / "broken.json").write_text("{ not valid json")
    save_skill_record(_record())
    assert {r.id for r in list_skill_records()} == {"coder"}
