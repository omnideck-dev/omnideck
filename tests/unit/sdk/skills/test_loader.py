"""Tests for the load_skill meta-tool.

load_skill resolves a skill by name from the store and adds it (tools + prompt)
to the active AgentState. These mock ``tool_categories`` and isolate the store.
"""

import pytest

from sdk.skills._store import SkillRecord, save_skill_record
from sdk.skills._tools import list_available_skills, load_skill
from sdk.skills.agent_state import AgentState, _active_agent_state
from sdk.tools._categories import ToolCategory


def _make_tool(name: str):
    async def tool() -> str:
        return name

    tool.__name__ = name
    return tool


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Temp skill store, with a fixed 'coding' tool category."""
    monkeypatch.setattr("sdk.skills._store._skills_dir", lambda: tmp_path / "skills")

    async def _cats():
        return {"coding": ToolCategory("coding", "Coding", "", [_make_tool("new_tool")])}

    monkeypatch.setattr("sdk.tools._categories.tool_categories", _cats)


@pytest.fixture()
def agent_state():
    state = AgentState([_make_tool("preexisting")])
    token = _active_agent_state.set(state)
    yield state
    _active_agent_state.reset(token)


@pytest.mark.unit
async def test_load_adds_tools(agent_state):
    save_skill_record(SkillRecord(id="test_sk", name="test_sk", prompt="Use these.", tool_categories=["coding"]))
    result = await load_skill("test_sk")
    assert "new_tool" in {t.__name__ for t in agent_state.tools}
    assert "test_sk" in agent_state.loaded_skill_ids
    assert "Loaded" in result


@pytest.mark.unit
async def test_load_returns_confirmation(agent_state):
    save_skill_record(SkillRecord(id="prompted", name="prompted", prompt="Follow this workflow.", tool_categories=[]))
    result = await load_skill("prompted")
    assert "Loaded" in result
    assert "system prompt" in result


@pytest.mark.unit
async def test_already_loaded(agent_state):
    save_skill_record(SkillRecord(id="once", name="once", tool_categories=["coding"]))
    await load_skill("once")
    result = await load_skill("once")
    assert "already loaded" in result


@pytest.mark.unit
async def test_unknown_skill_lists_available(agent_state):
    save_skill_record(SkillRecord(id="real", name="real", tool_categories=["coding"]))
    result = await load_skill("bogus")
    assert "Unknown skill 'bogus'" in result
    assert "Available: real" in result


@pytest.mark.unit
def test_list_available_lists_saved_skills():
    save_skill_record(SkillRecord(id="a", name="alpha", description="first"))
    save_skill_record(SkillRecord(id="b", name="beta", description="second"))
    result = list_available_skills()
    assert "alpha: first" in result
    assert "beta: second" in result


@pytest.mark.unit
async def test_no_active_agent_state():
    token = _active_agent_state.set(None)
    try:
        result = await load_skill("anything")
        assert "Error" in result
    finally:
        _active_agent_state.reset(token)
