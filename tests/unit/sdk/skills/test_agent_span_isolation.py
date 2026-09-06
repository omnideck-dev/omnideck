"""Tests that agent_span properly scopes the AgentCapabilities ContextVar."""

import pytest

from sdk.events._context import agent_span
from sdk.agent_capabilities import AgentCapabilities, _active_agent_capabilities


def _make_tool(name: str):
    async def tool() -> str:
        return name
    tool.__name__ = name
    return tool


@pytest.mark.unit
class TestAgentSpanAgentCapabilitiesIsolation:
    """Verify agent_span resets and restores the AgentCapabilities ContextVar."""

    @pytest.mark.asyncio
    async def test_agent_span_creates_fresh_agent_capabilities(self):
        """Inside an agent_span, a fresh AgentCapabilities is created."""
        parent = AgentCapabilities([_make_tool("parent_tool")])
        token = _active_agent_capabilities.set(parent)
        try:
            async with agent_span("child"):
                child = _active_agent_capabilities.get()
                assert child is not None
                assert child is not parent
                assert child.tools == []
        finally:
            _active_agent_capabilities.reset(token)

    @pytest.mark.asyncio
    async def test_agent_span_restores_parent(self):
        """After exiting agent_span, the parent's AgentCapabilities is restored."""
        parent = AgentCapabilities([_make_tool("parent_tool")])
        token = _active_agent_capabilities.set(parent)
        try:
            async with agent_span("child"):
                child = _active_agent_capabilities.get()
                assert child is not parent

            assert _active_agent_capabilities.get() is parent
        finally:
            _active_agent_capabilities.reset(token)

    @pytest.mark.asyncio
    async def test_nested_spans(self):
        """Nested agent_spans each get their own isolated scope."""
        root = AgentCapabilities([_make_tool("root")])
        token = _active_agent_capabilities.set(root)
        try:
            async with agent_span("level1", agent_capabilities=AgentCapabilities([_make_tool("l1")])):
                level1 = _active_agent_capabilities.get()
                assert level1 is not root
                assert len(level1.tools) == 1

                async with agent_span("level2", agent_capabilities=AgentCapabilities([_make_tool("l2")])):
                    level2 = _active_agent_capabilities.get()
                    assert level2 is not level1
                    assert len(level2.tools) == 1

                assert _active_agent_capabilities.get() is level1

            assert _active_agent_capabilities.get() is root
        finally:
            _active_agent_capabilities.reset(token)

    @pytest.mark.asyncio
    async def test_default_creates_empty_agent_capabilities(self):
        """Without any setup, agent_span creates an empty AgentCapabilities."""
        async with agent_span("clean"):
            ls = _active_agent_capabilities.get()
            assert ls is not None
            assert ls.tools == []
        assert _active_agent_capabilities.get() is None
