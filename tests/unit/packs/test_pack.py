"""Tests for the export/import pack logic.

Covers building profile and skill packs (with the include-skills and
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
from packs import (
    PACK_KIND,
    Pack,
    build_profile_pack,
    build_skill_pack,
    import_pack,
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
def test_build_profile_pack_missing_profile_raises():
    with pytest.raises(KeyError):
        build_profile_pack("nope", include_skills=False, include_model=True)


@pytest.mark.unit
def test_build_profile_pack_carries_all_settings():
    save_agent_profile(_profile(system_prompt="secret prompt", temperature=0.4))
    pack = build_profile_pack("researcher", include_skills=False, include_model=True)
    assert pack.kind == PACK_KIND
    assert len(pack.profiles) == 1
    assert pack.skills == []
    p = pack.profiles[0]
    assert p.system_prompt == "secret prompt"
    assert p.temperature == 0.4
    assert p.provider == "anthropic"
    assert p.model == "claude-x"


@pytest.mark.unit
def test_build_profile_pack_exclude_model_clears_provider_and_model_but_keeps_prompt():
    save_agent_profile(_profile(system_prompt="always here"))
    pack = build_profile_pack("researcher", include_skills=False, include_model=False)
    p = pack.profiles[0]
    assert p.provider == ""
    assert p.model == ""
    assert p.system_prompt == "always here"


@pytest.mark.unit
def test_build_profile_pack_exclude_model_clears_model_bound_inference_settings():
    save_agent_profile(
        _profile(
            temperature=0.4,
            reasoning_effort="high",
            context_window=8000,
            # App-orchestration setting, not tied to a specific model, so it stays.
            max_iterations=12,
        )
    )
    pack = build_profile_pack("researcher", include_skills=False, include_model=False)
    p = pack.profiles[0]
    assert p.temperature is None
    assert p.reasoning_effort is None
    assert p.context_window is None
    assert p.max_iterations == 12


@pytest.mark.unit
def test_build_profile_pack_include_model_keeps_inference_settings():
    save_agent_profile(_profile(temperature=0.4, context_window=8000))
    pack = build_profile_pack("researcher", include_skills=False, include_model=True)
    p = pack.profiles[0]
    assert p.temperature == 0.4
    assert p.context_window == 8000


@pytest.mark.unit
def test_build_profile_pack_include_skills_embeds_attached_records():
    save_skill_record(_skill(id="coder", name="Coder"))
    save_skill_record(_skill(id="searcher", name="Searcher", tool_categories=["webfetch"]))
    save_agent_profile(_profile(skills=["coder", "searcher"]))
    pack = build_profile_pack("researcher", include_skills=True, include_model=True)
    assert {s.id for s in pack.skills} == {"coder", "searcher"}


@pytest.mark.unit
def test_build_profile_pack_include_skills_skips_dangling_reference():
    save_skill_record(_skill(id="coder", name="Coder"))
    save_agent_profile(_profile(skills=["coder", "ghost"]))
    pack = build_profile_pack("researcher", include_skills=True, include_model=True)
    assert {s.id for s in pack.skills} == {"coder"}


@pytest.mark.unit
def test_build_profile_pack_without_include_skills_leaves_skills_empty():
    save_skill_record(_skill())
    save_agent_profile(_profile(skills=["coder"]))
    pack = build_profile_pack("researcher", include_skills=False, include_model=True)
    assert pack.skills == []


@pytest.mark.unit
def test_build_skill_pack_missing_skill_raises():
    with pytest.raises(KeyError):
        build_skill_pack("nope")


@pytest.mark.unit
def test_build_skill_pack_packs_single_skill():
    save_skill_record(_skill())
    pack = build_skill_pack("coder")
    assert pack.profiles == []
    assert len(pack.skills) == 1
    assert pack.skills[0].name == "Coder"


@pytest.mark.unit
def test_import_pack_rejects_foreign_kind():
    with pytest.raises(ValueError, match="omnideck pack"):
        import_pack(Pack(kind="something.else"))


@pytest.mark.unit
def test_import_pack_rejects_newer_version():
    with pytest.raises(ValueError, match="newer version"):
        import_pack(Pack(version=999))


@pytest.mark.unit
def test_import_pack_rejects_empty():
    with pytest.raises(ValueError, match="no agents or skills"):
        import_pack(Pack())


@pytest.mark.unit
def test_import_pack_skill_creates_fresh_id():
    pack = Pack(skills=[_skill(id="coder", name="Coder")])
    summary = import_pack(pack)
    assert len(summary.skills) == 1
    created = summary.skills[0]
    assert created.id != "coder"
    assert created.name == "Coder"
    assert get_skill_record(created.id) is not None


@pytest.mark.unit
def test_import_pack_dedupes_colliding_skill_name():
    save_skill_record(_skill(id="existing", name="Coder"))
    summary = import_pack(Pack(skills=[_skill(id="coder", name="Coder")]))
    assert summary.skills[0].name == "Coder (imported)"
    # Both records now exist with distinct ids and names.
    names = {r.name for r in list_skill_records()}
    assert names == {"Coder", "Coder (imported)"}


@pytest.mark.unit
def test_import_pack_dedupes_second_collision():
    save_skill_record(_skill(id="a", name="Coder"))
    save_skill_record(_skill(id="b", name="Coder (imported)"))
    summary = import_pack(Pack(skills=[_skill(id="coder", name="Coder")]))
    assert summary.skills[0].name == "Coder (imported 2)"


@pytest.mark.unit
def test_import_pack_profile_creates_fresh_id():
    summary = import_pack(Pack(profiles=[_profile(id="researcher")]))
    assert len(summary.profiles) == 1
    created = summary.profiles[0]
    assert created.id != "researcher"
    assert get_agent_profile(created.id) is not None


@pytest.mark.unit
def test_import_pack_dedupes_colliding_profile_name():
    save_agent_profile(_profile(id="existing", name="Researcher"))
    summary = import_pack(Pack(profiles=[_profile(id="researcher", name="Researcher")]))
    assert summary.profiles[0].name == "Researcher (imported)"


@pytest.mark.unit
def test_import_pack_remaps_profile_skill_references():
    # A profile pack carrying its skill: the imported profile must point at the
    # newly created skill id, not the original.
    pack = Pack(
        profiles=[_profile(id="researcher", skills=["coder"])],
        skills=[_skill(id="coder", name="Coder")],
    )
    summary = import_pack(pack)
    new_skill_id = summary.skills[0].id
    assert summary.profiles[0].skills == [new_skill_id]


@pytest.mark.unit
def test_import_pack_keeps_unpacked_skill_reference_as_is():
    # A reference to a skill not present in the pack is left untouched — it may
    # already exist on the target install.
    summary = import_pack(Pack(profiles=[_profile(id="r", skills=["local_skill"])]))
    assert summary.profiles[0].skills == ["local_skill"]


@pytest.mark.unit
def test_roundtrip_export_then_import():
    save_skill_record(_skill(id="coder", name="Coder"))
    save_agent_profile(_profile(id="researcher", skills=["coder"], system_prompt="hello"))
    pack = build_profile_pack("researcher", include_skills=True, include_model=True)

    summary = import_pack(pack)
    assert len(summary.profiles) == 1
    assert len(summary.skills) == 1
    imported = summary.profiles[0]
    assert imported.system_prompt == "hello"
    assert imported.skills == [summary.skills[0].id]
    # Originals still present alongside the imported copies.
    assert len(list_agent_profiles(include_disabled=True)) == 2
    assert len(list_skill_records()) == 2
