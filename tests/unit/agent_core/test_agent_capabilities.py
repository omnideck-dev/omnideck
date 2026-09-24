"""Tests for AgentCapabilities — base tools + dynamic skill attachment."""

import pytest

from agent_core.agent_capabilities import AgentCapabilities
from agent_core.capabilities import AgentCapability
from agent_core.skills._registry import Skill


def _make_tool(name: str):
    """Create a dummy tool function with a given __name__."""

    async def tool() -> str:
        return name

    tool.__name__ = name
    return tool


def _make_skill(name: str, tool_names: list[str], prompt: str = "p") -> Skill:
    return Skill(
        name=name,
        description=f"desc_{name}",
        prompt=prompt,
        tools=[_make_tool(n) for n in tool_names],
    )


@pytest.mark.unit
class TestAgentCapabilities:
    """Tests for AgentCapabilities add, dedup, find, and prompt building."""

    def test_init_copies_tools(self):
        """AgentCapabilities makes a copy of the input list."""
        original = [_make_tool("a")]
        ls = AgentCapabilities(original)
        assert len(ls.tools) == 1
        original.append(_make_tool("b"))
        assert len(ls.tools) == 1

    def test_add_adds_tools(self):
        """Adding a skill adds its tools."""
        sk = _make_skill("sk", ["b", "c"])
        ls = AgentCapabilities([_make_tool("a")])
        ls.add(sk)
        assert {t.__name__ for t in ls.tools} == {"a", "b", "c"}

    def test_add_deduplicates(self):
        """Tools with the same __name__ are not added twice."""
        sk = _make_skill("sk", ["a", "b"])
        ls = AgentCapabilities([_make_tool("a")])
        ls.add(sk)
        assert len(ls.tools) == 2  # a (base) + b (skill), not a again

    def test_capability_adds_tools_and_prompt_without_becoming_a_skill(self):
        """Application capabilities compose alongside skills but remain separate."""
        state = AgentCapabilities([_make_tool("base")])
        state.add_capability(
            AgentCapability(
                id="browser",
                name="Browser",
                prompt="Browse safely.",
                tools=[_make_tool("open_url")],
            )
        )

        assert {tool.__name__ for tool in state.tools} == {"base", "open_url"}
        assert state.skill_ids == frozenset()
        assert "### Browser\nBrowse safely." in state.build_prompt_extensions()

    def test_add_tracks_skill_id(self):
        """skill_ids reflects every attached skill."""
        browser = _make_skill("browser", ["open_url"])
        coder = _make_skill("coder", ["read_file"])
        ls = AgentCapabilities([])
        assert ls.skill_ids == frozenset()
        ls.add(browser)
        assert ls.skill_ids == frozenset({"browser"})
        ls.add(coder)
        assert ls.skill_ids == frozenset({"browser", "coder"})

    def test_load_marks_persistable_delta(self):
        """load() skills count toward loaded_skill_ids; add() baseline skills are
        attached but not part of the persisted delta."""
        base = _make_skill("base", ["a"])
        extra = _make_skill("extra", ["b"])
        ls = AgentCapabilities([])
        ls.add(base)  # profile baseline
        ls.load(extra)  # loaded at runtime
        assert ls.skill_ids == frozenset({"base", "extra"})
        assert ls.loaded_skill_ids == frozenset({"extra"})

    def test_add_idempotent(self):
        """Adding the same skill twice is a no-op."""
        sk = _make_skill("sk", ["t"])
        ls = AgentCapabilities([])
        ls.add(sk)
        ls.add(sk)
        assert len(ls.tools) == 1
        assert ls.skill_ids == frozenset({"sk"})

    def test_skill_ids_is_frozen(self):
        """skill_ids returns a frozenset (immutable snapshot)."""
        sk = _make_skill("x", [])
        ls = AgentCapabilities([])
        ls.add(sk)
        assert isinstance(ls.skill_ids, frozenset)

    def test_build_prompt_extensions_empty(self):
        """build_prompt_extensions returns empty string with no skills loaded."""
        ls = AgentCapabilities([_make_tool("a")])
        assert ls.build_prompt_extensions() == ""

    def test_build_prompt_extensions(self):
        """build_prompt_extensions includes loaded skill prompts."""
        browser = _make_skill("browser", ["open_url"], prompt="Browse the web.")
        coder = _make_skill("coder", ["read_file"], prompt="Edit files.")
        ls = AgentCapabilities([])
        ls.add(browser)
        ls.add(coder)
        prompt = ls.build_prompt_extensions()
        assert "── Capabilities & Skills ──" in prompt
        assert "### browser" in prompt
        assert "Browse the web." in prompt
        assert "### coder" in prompt
        assert "Edit files." in prompt
