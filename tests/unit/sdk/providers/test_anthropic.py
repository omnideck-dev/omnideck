"""Tests for AnthropicProvider message conversion and request kwargs.

These exercise the pure helpers and ``_build_kwargs`` without constructing a
real client, so the optional ``anthropic`` package is not required.
"""

import pytest

from sdk.providers._anthropic import (
    AnthropicProvider,
    _convert_messages,
    _convert_tools,
)


def _sample_tool(query: str, limit: int = 10) -> str:
    """Search for things.

    Args:
        query: What to search for.
        limit: Max results.
    """
    return query


def _build_kwargs(**overrides):
    """Call ``_build_kwargs`` on an uninitialized provider instance."""
    provider = AnthropicProvider.__new__(AnthropicProvider)
    params = {
        "model": "claude-sonnet-4",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": None,
        "options": None,
        "think": False,
    }
    params.update(overrides)
    return provider._build_kwargs(**params)


# ---------------------------------------------------------------------------
# _convert_messages
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConvertMessages:
    def test_system_message_extracted(self):
        system, converted = _convert_messages([
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "hello"},
        ])
        assert system == "be brief"
        assert converted == [{"role": "user", "content": "hello"}]

    def test_assistant_tool_calls_become_tool_use_blocks(self):
        _, converted = _convert_messages([
            {
                "role": "assistant",
                "content": "working",
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "search", "arguments": {"q": "x"}}},
                ],
            },
        ])
        blocks = converted[0]["content"]
        assert blocks[0] == {"type": "text", "text": "working"}
        assert blocks[1] == {
            "type": "tool_use",
            "id": "call_1",
            "name": "search",
            "input": {"q": "x"},
        }

    def test_tool_result_becomes_user_tool_result_block(self):
        _, converted = _convert_messages([
            {"role": "tool", "tool_call_id": "call_1", "content": "result text"},
        ])
        assert converted == [{
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "call_1",
                "content": "result text",
            }],
        }]


# ---------------------------------------------------------------------------
# _build_kwargs — prompt caching must use a content block, never a top-level
# field (the Messages API rejects a top-level cache_control).
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildKwargsCaching:
    def test_no_top_level_cache_control(self):
        kwargs = _build_kwargs()
        assert "cache_control" not in kwargs

    def test_system_prompt_carries_cache_breakpoint(self):
        kwargs = _build_kwargs(messages=[
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "hi"},
        ])
        assert kwargs["system"] == [{
            "type": "text",
            "text": "be brief",
            "cache_control": {"type": "ephemeral"},
        }]

    def test_cache_breakpoint_falls_back_to_last_tool(self):
        kwargs = _build_kwargs(
            messages=[{"role": "user", "content": "hi"}],
            tools=[_sample_tool],
        )
        # No system prompt, so the breakpoint goes on the final tool.
        assert "system" not in kwargs
        assert kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral"}

    def test_tools_without_system_have_single_breakpoint(self):
        kwargs = _build_kwargs(tools=[_sample_tool])
        marked = [t for t in kwargs["tools"] if "cache_control" in t]
        assert len(marked) == 1


# ---------------------------------------------------------------------------
# _build_kwargs — defaults and options passthrough
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildKwargsOptions:
    def test_default_max_tokens(self):
        kwargs = _build_kwargs()
        assert kwargs["max_tokens"] == 16384

    def test_options_passthrough(self):
        kwargs = _build_kwargs(options={"temperature": 0.2, "top_p": 0.9, "max_tokens": 256})
        assert kwargs["max_tokens"] == 256
        assert kwargs["temperature"] == 0.2
        assert kwargs["top_p"] == 0.9

    def test_think_enables_thinking_and_forces_temperature(self):
        kwargs = _build_kwargs(think=True, options={"max_tokens": 4096})
        assert kwargs["temperature"] == 1
        assert kwargs["thinking"]["type"] == "enabled"
        assert kwargs["thinking"]["budget_tokens"] == 2048


@pytest.mark.unit
class TestConvertTools:
    def test_tool_schema_shape(self):
        tools = _convert_tools([_sample_tool])
        assert tools[0]["name"] == "_sample_tool"
        assert "input_schema" in tools[0]
        assert tools[0]["input_schema"]["type"] == "object"
