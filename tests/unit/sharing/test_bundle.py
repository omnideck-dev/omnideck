"""Tests for the export/import bundle logic.

Covers building profile and skill bundles (with the include-skills and
include-model options) and importing them back — id remapping, skill-name
de-duplication, and rewriting a profile's skill references onto imported copies.
"""

import pytest

from agents._agent_profiles import (
    AgentProfile,
    get_agent_profile,
    list_agent_profiles,
    save_agent_profile,
)
from sharing import (
    BUNDLE_KIND,
    Bundle,
    build_profile_bundle,
    build_skill_bundle,
    import_bundle,
)
from sdk.skills._store import (
    SkillRecord,
    get_skill_record,
    list_skill_records,
    save_skill_record,
)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Point both stores at temp directories per test."""
    monkeypatch.setattr(
        "agents._agent_profiles._profiles_dir", lambda: tmp_path / "agent_profiles"
    )
    monkeypatch.setattr("sdk.skills._store._skills_dir", lambda: tmp_path / "skills")


def _profile(**overrides) -> AgentProfile:
    defaults = {
        "id": "researcher",
        "name": "Researcher",
        "system_prompt": "You research.",
        "provider": "anthropic",
        "model": "claude-x",
    }
    defaults.update(overrides)
    return AgentProfile(**defaults)


def _skill(**overrides) -> SkillRecord:
    defaults = {"id": "coder", "name": "Coder", "prompt": "Write code.", "tool_categories": ["coding"]}
    defaults.update(overrides)
    return SkillRecord(**defaults)


@pytest.mark.unit
class TestBuildProfileBundle:
    def test_missing_profile_raises(self):
        with pytest.raises(KeyError):
            build_profile_bundle("nope", include_skills=False, include_model=True)

    def test_basic_bundle_carries_all_settings(self):
        save_agent_profile(_profile(system_prompt="secret prompt", temperature=0.4))
        bundle = build_profile_bundle("researcher", include_skills=False, include_model=True)
        assert bundle.kind == BUNDLE_KIND
        assert len(bundle.profiles) == 1
        assert bundle.skills == []
        p = bundle.profiles[0]
        assert p.system_prompt == "secret prompt"
        assert p.temperature == 0.4
        assert p.provider == "anthropic"
        assert p.model == "claude-x"

    def test_exclude_model_clears_provider_and_model_but_keeps_prompt(self):
        save_agent_profile(_profile(system_prompt="always here"))
        bundle = build_profile_bundle("researcher", include_skills=False, include_model=False)
        p = bundle.profiles[0]
        assert p.provider == ""
        assert p.model == ""
        assert p.system_prompt == "always here"

    def test_include_skills_embeds_attached_records(self):
        save_skill_record(_skill(id="coder", name="Coder"))
        save_skill_record(_skill(id="searcher", name="Searcher", tool_categories=["webfetch"]))
        save_agent_profile(_profile(skills=["coder", "searcher"]))
        bundle = build_profile_bundle("researcher", include_skills=True, include_model=True)
        assert {s.id for s in bundle.skills} == {"coder", "searcher"}

    def test_include_skills_skips_dangling_reference(self):
        save_skill_record(_skill(id="coder", name="Coder"))
        save_agent_profile(_profile(skills=["coder", "ghost"]))
        bundle = build_profile_bundle("researcher", include_skills=True, include_model=True)
        assert {s.id for s in bundle.skills} == {"coder"}

    def test_no_include_skills_leaves_skills_empty(self):
        save_skill_record(_skill())
        save_agent_profile(_profile(skills=["coder"]))
        bundle = build_profile_bundle("researcher", include_skills=False, include_model=True)
        assert bundle.skills == []


@pytest.mark.unit
class TestBuildSkillBundle:
    def test_missing_skill_raises(self):
        with pytest.raises(KeyError):
            build_skill_bundle("nope")

    def test_bundles_single_skill(self):
        save_skill_record(_skill())
        bundle = build_skill_bundle("coder")
        assert bundle.profiles == []
        assert len(bundle.skills) == 1
        assert bundle.skills[0].name == "Coder"


@pytest.mark.unit
class TestImportBundle:
    def test_rejects_foreign_kind(self):
        with pytest.raises(ValueError, match="kind"):
            import_bundle(Bundle(kind="something.else"))

    def test_rejects_newer_version(self):
        with pytest.raises(ValueError, match="version"):
            import_bundle(Bundle(version=999))

    def test_import_skill_creates_fresh_id(self):
        bundle = Bundle(skills=[_skill(id="coder", name="Coder")])
        summary = import_bundle(bundle)
        assert len(summary.skills) == 1
        created = summary.skills[0]
        assert created.id != "coder"
        assert created.name == "Coder"
        assert get_skill_record(created.id) is not None

    def test_import_dedupes_colliding_skill_name(self):
        save_skill_record(_skill(id="existing", name="Coder"))
        summary = import_bundle(Bundle(skills=[_skill(id="coder", name="Coder")]))
        assert summary.skills[0].name == "Coder (imported)"
        # Both records now exist with distinct ids and names.
        names = {r.name for r in list_skill_records()}
        assert names == {"Coder", "Coder (imported)"}

    def test_import_dedupes_second_collision(self):
        save_skill_record(_skill(id="a", name="Coder"))
        save_skill_record(_skill(id="b", name="Coder (imported)"))
        summary = import_bundle(Bundle(skills=[_skill(id="coder", name="Coder")]))
        assert summary.skills[0].name == "Coder (imported 2)"

    def test_import_profile_creates_fresh_id(self):
        summary = import_bundle(Bundle(profiles=[_profile(id="researcher")]))
        assert len(summary.profiles) == 1
        created = summary.profiles[0]
        assert created.id != "researcher"
        assert get_agent_profile(created.id) is not None

    def test_import_dedupes_colliding_profile_name(self):
        save_agent_profile(_profile(id="existing", name="Researcher"))
        summary = import_bundle(Bundle(profiles=[_profile(id="researcher", name="Researcher")]))
        assert summary.profiles[0].name == "Researcher (imported)"

    def test_import_remaps_profile_skill_references(self):
        # A profile bundle carrying its skill: the imported profile must point
        # at the newly created skill id, not the original.
        bundle = Bundle(
            profiles=[_profile(id="researcher", skills=["coder"])],
            skills=[_skill(id="coder", name="Coder")],
        )
        summary = import_bundle(bundle)
        new_skill_id = summary.skills[0].id
        assert summary.profiles[0].skills == [new_skill_id]

    def test_import_keeps_unbundled_skill_reference_as_is(self):
        # A reference to a skill not present in the bundle is left untouched —
        # it may already exist on the target install.
        summary = import_bundle(Bundle(profiles=[_profile(id="r", skills=["local_skill"])]))
        assert summary.profiles[0].skills == ["local_skill"]

    def test_roundtrip_export_then_import(self):
        save_skill_record(_skill(id="coder", name="Coder"))
        save_agent_profile(_profile(id="researcher", skills=["coder"], system_prompt="hello"))
        bundle = build_profile_bundle("researcher", include_skills=True, include_model=True)

        summary = import_bundle(bundle)
        assert len(summary.profiles) == 1
        assert len(summary.skills) == 1
        imported = summary.profiles[0]
        assert imported.system_prompt == "hello"
        assert imported.skills == [summary.skills[0].id]
        # Originals still present alongside the imported copies.
        assert len(list_agent_profiles(include_disabled=True)) == 2
        assert len(list_skill_records()) == 2
