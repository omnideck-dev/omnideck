"""Tests for the skill record store.

A SkillRecord is the persisted form of a skill: prompt text plus the category
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
    defaults = {"id": "coder", "name": "Coder", "prompt": "Write code.", "categories": ["coding"]}
    defaults.update(overrides)
    return SkillRecord(**defaults)


@pytest.mark.unit
class TestSkillRecordModel:
    def test_minimal_defaults(self):
        r = SkillRecord(id="x", name="X")
        assert r.categories == []
        assert r.enabled is True

    def test_roundtrip_serialization(self):
        r = _record(categories=["coding", "memory"], description="d")
        r2 = SkillRecord.model_validate(json.loads(json.dumps(r.model_dump())))
        assert r2 == r


@pytest.mark.unit
class TestSkillCRUD:
    def test_save_and_get(self):
        save_skill_record(_record())
        loaded = get_skill_record("coder")
        assert loaded is not None
        assert loaded.name == "Coder"
        assert loaded.categories == ["coding"]

    def test_get_nonexistent_returns_none(self):
        assert get_skill_record("nope") is None

    def test_list_empty(self):
        assert list_skill_records() == []

    def test_list_sorted_by_name(self):
        save_skill_record(_record(id="z", name="Zebra"))
        save_skill_record(_record(id="a", name="Alpha"))
        assert [r.name for r in list_skill_records()] == ["Alpha", "Zebra"]

    def test_delete(self):
        save_skill_record(_record())
        assert delete_skill_record("coder") is True
        assert get_skill_record("coder") is None

    def test_delete_nonexistent_returns_false(self):
        assert delete_skill_record("nope") is False

    def test_save_overwrites_same_id(self):
        save_skill_record(_record(prompt="v1"))
        save_skill_record(_record(prompt="v2"))
        assert get_skill_record("coder").prompt == "v2"

    def test_stored_one_file_per_id(self, tmp_path):
        save_skill_record(_record())
        assert (tmp_path / "skills" / "coder.json").is_file()


@pytest.mark.unit
class TestNameUniqueness:
    def test_duplicate_name_under_different_id_rejected(self):
        save_skill_record(_record(id="coder", name="Coder"))
        with pytest.raises(ValueError, match="name"):
            save_skill_record(_record(id="other", name="Coder"))

    def test_rename_same_id_is_allowed(self):
        save_skill_record(_record(id="coder", name="Coder"))
        save_skill_record(_record(id="coder", name="Coder 2"))
        assert get_skill_record("coder").name == "Coder 2"


@pytest.mark.unit
class TestBadFiles:
    def test_broken_file_is_skipped(self, tmp_path):
        d = tmp_path / "skills"
        d.mkdir(parents=True)
        (d / "broken.json").write_text("{ not valid json")
        save_skill_record(_record())
        assert {r.id for r in list_skill_records()} == {"coder"}

    def test_legacy_json_without_new_fields_loads_with_defaults(self, tmp_path):
        d = tmp_path / "skills"
        d.mkdir(parents=True)
        (d / "old.json").write_text(json.dumps({"id": "old", "name": "Old"}))
        r = get_skill_record("old")
        assert r is not None
        assert r.enabled is True
        assert r.categories == []
