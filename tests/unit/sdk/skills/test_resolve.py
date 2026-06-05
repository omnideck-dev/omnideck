"""Tests for skill resolution and agent-tool composition.

resolve_skill maps a stored record's tool category ids to live tools via
``tool_categories`` and bundles them into a runtime Skill. compose_agent_tools
assembles a profile's base tools (spawn/load gated by its autonomy toggles) plus
its skills' tools, deduplicated. These mock ``tool_categories`` directly — what
each category resolves to is the category registry's concern, tested separately.
"""

import pytest

from agents._agent_profiles import AgentProfile
from sdk.skills._resolve import compose_agent_tools, resolve_skill, resolve_skill_by_name
from sdk.skills._store import SkillRecord, save_skill_record
from sdk.tools._categories import ToolCategory


def _tool(name):
    def f():
        ...

    f.__name__ = name
    return f


def _categories() -> dict[str, ToolCategory]:
    return {
        "coding": ToolCategory("coding", "Coding", "", [_tool("read_file"), _tool("run_bash_cmd")]),
        "memory": ToolCategory("memory", "Memory", "", [_tool("remember")]),
        "email": ToolCategory("email", "Email", "", [_tool("search_email")]),
    }


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Temp skill store, and a fixed set of resolved tool categories."""
    monkeypatch.setattr("sdk.skills._store._skills_dir", lambda: tmp_path / "skills")

    async def _cats():
        return _categories()

    monkeypatch.setattr("sdk.skills._resolve.tool_categories", _cats)


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
async def test_compose_includes_base_tools():
    names = _names(await compose_agent_tools(_profile(skills=[])))
    assert {"save_to_scratchpad", "datetime_tool"} <= names


@pytest.mark.unit
async def test_compose_honors_allow_spawn():
    on = _names(await compose_agent_tools(_profile(allow_spawn=True)))
    off = _names(await compose_agent_tools(_profile(allow_spawn=False)))
    assert "spawn_agent" in on
    assert "spawn_agent" not in off


@pytest.mark.unit
async def test_compose_honors_allow_load_skills():
    on = _names(await compose_agent_tools(_profile(allow_load_skills=True)))
    off = _names(await compose_agent_tools(_profile(allow_load_skills=False)))
    assert "load_skill" in on
    assert "load_skill" not in off


@pytest.mark.unit
async def test_compose_resolves_profile_skills():
    save_skill_record(SkillRecord(id="coder", name="Coder", tool_categories=["coding"]))
    names = _names(await compose_agent_tools(_profile(skills=["coder"])))
    assert "read_file" in names


@pytest.mark.unit
async def test_compose_skips_unknown_skill():
    names = _names(await compose_agent_tools(_profile(skills=["ghost"])))
    assert "datetime_tool" in names  # base intact, no crash


@pytest.mark.unit
async def test_compose_dedups_by_name():
    save_skill_record(SkillRecord(id="m1", name="M1", tool_categories=["memory"]))
    save_skill_record(SkillRecord(id="m2", name="M2", tool_categories=["memory"]))
    tools = await compose_agent_tools(_profile(skills=["m1", "m2"]))
    assert [t.__name__ for t in tools].count("remember") == 1
