"""Tests for skill resolution and agent-state composition.

resolve_skill maps a stored record's tool category ids to live tools via
``tool_categories`` and bundles them into a runtime Skill. build_agent_state
assembles a profile's AgentState: base tools (spawn/load gated by its autonomy
toggles) plus its skills added as units, so prompts and tools both apply. These
mock ``tool_categories`` directly — what each category resolves to is the
category registry's concern, tested separately.
"""

import pytest

from agents._agent_profiles import AgentProfile
from sdk.agent_state import (
    _restore_persisted_loaded_skills,
    AgentState,
    build_agent_state,
    persist_loaded_skills,
)
from sdk.skills._resolve import (
    resolve_skill,
    resolve_skill_by_name,
)
from sdk.skills._store import SkillRecord, save_skill_record
from sdk.skills._tool_categories import ToolCategory


def _tool(name):
    def f(): ...

    f.__name__ = name
    return f


def _categories() -> dict[str, ToolCategory]:
    return {
        "coding": ToolCategory("coding", "Coding", "", [_tool("read_file"), _tool("run_bash_cmd")]),
        "memory": ToolCategory("memory", "Memory", "", [_tool("remember")]),
        "email": ToolCategory("email", "Email", "", [_tool("search_email")]),
        "browser": ToolCategory("browser", "Browser", "", [_tool("open_url")]),
    }


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Temp skill store, and a fixed set of resolved tool categories."""
    monkeypatch.setattr("sdk.skills._store._skills_dir", lambda: tmp_path / "skills")

    async def _cats():
        return _categories()

    monkeypatch.setattr("sdk.skills._resolve.tool_categories", _cats)
    monkeypatch.setattr("tools.browser.capability.tool_categories", _cats)


def _names(tools):
    return {t.__name__ for t in tools}


def _profile(**overrides) -> AgentProfile:
    base = {"id": "p", "name": "P", "model": "m"}
    base.update(overrides)
    return AgentProfile(**base)


@pytest.mark.unit
async def test_resolve_builds_prompt_and_tools():
    save_skill_record(SkillRecord(id="coder", name="Coder", prompt="Write code.", tool_categories=["coding"]))
    skill = await resolve_skill("coder")
    assert skill is not None
    assert (skill.id, skill.name, skill.prompt) == ("coder", "Coder", "Write code.")
    assert "read_file" in _names(skill.tools)


@pytest.mark.unit
async def test_resolve_unknown_id_returns_none():
    assert await resolve_skill("nope") is None


@pytest.mark.unit
async def test_resolve_unknown_category_contributes_nothing():
    save_skill_record(SkillRecord(id="x", name="X", tool_categories=["bogus"]))
    skill = await resolve_skill("x")
    assert skill.tools == []


@pytest.mark.unit
async def test_resolve_combines_multiple_categories():
    save_skill_record(SkillRecord(id="a", name="A", tool_categories=["coding", "email"]))
    names = _names((await resolve_skill("a")).tools)
    assert {"read_file", "search_email"} <= names


@pytest.mark.unit
async def test_resolve_rename_keeps_id_resolvable():
    save_skill_record(SkillRecord(id="coder", name="Coder", tool_categories=["coding"]))
    save_skill_record(SkillRecord(id="coder", name="Renamed", tool_categories=["coding"]))
    skill = await resolve_skill("coder")
    assert skill is not None
    assert skill.name == "Renamed"


@pytest.mark.unit
async def test_resolve_by_name():
    save_skill_record(SkillRecord(id="abc123", name="My Skill", tool_categories=["memory"]))
    skill = await resolve_skill_by_name("My Skill")
    assert skill is not None
    assert skill.id == "abc123"


@pytest.mark.unit
async def test_build_includes_base_tools():
    state = await build_agent_state(_profile(skills=[]))
    assert {"save_to_scratchpad", "datetime_tool"} <= _names(state.tools)


@pytest.mark.unit
async def test_build_honors_allow_spawn():
    on = _names((await build_agent_state(_profile(allow_spawn=True))).tools)
    off = _names((await build_agent_state(_profile(allow_spawn=False))).tools)
    assert "spawn_agent" in on
    assert "spawn_agent" not in off


@pytest.mark.unit
async def test_build_honors_allow_load_skills():
    on = _names((await build_agent_state(_profile(allow_load_skills=True))).tools)
    off = _names((await build_agent_state(_profile(allow_load_skills=False))).tools)
    assert "load_skill" in on
    assert "load_skill" not in off


@pytest.mark.unit
async def test_build_adds_profile_skill_tools():
    save_skill_record(SkillRecord(id="coder", name="Coder", tool_categories=["coding"]))
    state = await build_agent_state(_profile(skills=["coder"]))
    assert "read_file" in _names(state.tools)


@pytest.mark.unit
async def test_browser_selection_adds_application_capability():
    state = await build_agent_state(
        _profile(
            browser_profile_id="default",
        )
    )

    assert "open_url" in _names(state.tools)
    assert "Browser automation." in state.build_prompt_extensions()
    assert "browser" not in state.skill_ids


@pytest.mark.unit
async def test_stale_browser_skill_cannot_bypass_disabled_browser():
    save_skill_record(
        SkillRecord(
            id="browser",
            name="Browser",
            prompt="Browse websites.",
            tool_categories=["browser"],
        )
    )
    state = await build_agent_state(_profile(skills=["browser"], browser_profile_id=None))
    assert "open_url" not in _names(state.tools)
    assert "browser" not in state.skill_ids


@pytest.mark.unit
async def test_custom_skill_cannot_grant_browser_category():
    save_skill_record(
        SkillRecord(
            id="custom",
            name="Custom",
            tool_categories=["browser"],
        )
    )
    state = await build_agent_state(_profile(skills=["custom"], browser_profile_id=None))
    assert "open_url" not in _names(state.tools)


@pytest.mark.unit
async def test_build_profile_skills_stay_out_of_loaded_delta():
    """A profile's skills attach but aren't part of the persisted delta, so the
    profile is re-derived each turn and a profile edit isn't pinned to a
    conversation by stale metadata."""
    save_skill_record(SkillRecord(id="coder", name="Coder", tool_categories=["coding"]))
    state = await build_agent_state(_profile(skills=["coder"]))
    assert "coder" in state.skill_ids
    assert state.loaded_skill_ids == frozenset()


@pytest.mark.unit
async def test_build_adds_profile_skill_prompts():
    save_skill_record(SkillRecord(id="coder", name="Coder", prompt="Write code.", tool_categories=["coding"]))
    state = await build_agent_state(_profile(skills=["coder"]))
    section = state.build_prompt_extensions()
    assert "Coder" in section
    assert "Write code." in section


@pytest.mark.unit
async def test_build_skips_unknown_skill():
    state = await build_agent_state(_profile(skills=["ghost"]))
    assert "datetime_tool" in _names(state.tools)  # base intact, no crash


@pytest.mark.unit
async def test_build_dedups_tools_by_name():
    save_skill_record(SkillRecord(id="m1", name="M1", tool_categories=["memory"]))
    save_skill_record(SkillRecord(id="m2", name="M2", tool_categories=["memory"]))
    state = await build_agent_state(_profile(skills=["m1", "m2"]))
    assert [t.__name__ for t in state.tools].count("remember") == 1


@pytest.mark.unit
async def test_build_restores_conversation_loaded_skills(monkeypatch):
    """With a conversation id, skills loaded in earlier turns are restored on
    top of the profile's skills — read from conversation metadata."""
    save_skill_record(SkillRecord(id="coder", name="Coder", tool_categories=["coding"]))
    monkeypatch.setattr("conversations.load_loaded_skills", lambda cid: {"coder"})
    state = await build_agent_state(_profile(skills=[]), conversation_id="c1")
    assert "coder" in state.loaded_skill_ids
    assert "read_file" in _names(state.tools)


@pytest.mark.unit
async def test_build_without_conversation_id_skips_restore(monkeypatch):
    """No conversation id means no metadata read and no restored skills."""
    called = False

    def _spy(cid):
        nonlocal called
        called = True
        return {"coder"}

    monkeypatch.setattr("conversations.load_loaded_skills", _spy)
    state = await build_agent_state(_profile(skills=[]))
    assert called is False
    assert state.loaded_skill_ids == frozenset()


@pytest.mark.unit
async def test_persist_loaded_skills_writes_ids(monkeypatch):
    """persist_loaded_skills hands the state's loaded ids to the conversation store."""
    saved = {}
    monkeypatch.setattr(
        "conversations.save_loaded_skills",
        lambda cid, ids: saved.update(cid=cid, ids=ids),
    )
    save_skill_record(SkillRecord(id="coder", name="Coder", tool_categories=["coding"]))
    state = AgentState([])
    await _restore_persisted_loaded_skills(state, ["coder"])
    persist_loaded_skills(state, "c1")
    assert saved["cid"] == "c1"
    assert saved["ids"] == frozenset({"coder"})


@pytest.mark.unit
async def test_restore_skills_resolves_and_adds_by_id():
    save_skill_record(SkillRecord(id="coder", name="Coder", tool_categories=["coding"]))
    state = AgentState([])
    await _restore_persisted_loaded_skills(state, ["coder"])
    assert "coder" in state.loaded_skill_ids
    assert "read_file" in _names(state.tools)


@pytest.mark.unit
async def test_restore_skills_skips_already_loaded():
    save_skill_record(SkillRecord(id="coder", name="Coder", tool_categories=["coding"]))
    state = AgentState([])
    await _restore_persisted_loaded_skills(state, ["coder"])
    await _restore_persisted_loaded_skills(state, ["coder"])  # second restore is a no-op
    assert state.loaded_skill_ids == frozenset({"coder"})


@pytest.mark.unit
async def test_restore_skills_skips_unresolvable_id():
    state = AgentState([])
    await _restore_persisted_loaded_skills(state, ["ghost"])  # no such record — stale metadata
    assert state.loaded_skill_ids == frozenset()
