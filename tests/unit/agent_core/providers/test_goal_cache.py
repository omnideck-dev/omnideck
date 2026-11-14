"""Goal notifications and tool reads preserve append-only provider prefixes."""

import copy
import json

import pytest

from agent_core.context import GOAL_STATE_PREFIX
from agent_core.providers._anthropic import AnthropicProvider
from agent_core.providers._ollama import _build_ollama_kwargs
from agent_core.providers._openai import OpenAIProvider
from agent_core.providers._openai_responses import OpenAIResponsesProvider
from agent_core.providers._openrouter import OpenRouterProvider


def request(provider, messages):
    if provider == "ollama":
        return _build_ollama_kwargs("model", messages, None, None, False)
    cls, model = {
        "anthropic": (AnthropicProvider, "claude-sonnet-4-6"),
        "openrouter_claude": (OpenRouterProvider, "anthropic/claude-sonnet-4.6"),
        "openrouter_other": (OpenRouterProvider, "deepseek/deepseek-chat"),
        "openai_compat": (OpenAIProvider, "model"),
        "responses": (OpenAIResponsesProvider, "model"),
    }[provider]
    return cls.__new__(cls)._build_kwargs(model, messages, None, None, False)


def without_cache(value):
    if isinstance(value, dict):
        return {k: without_cache(v) for k, v in value.items() if k != "cache_control"}
    if isinstance(value, list):
        return [without_cache(v) for v in value]
    return value


@pytest.mark.parametrize("provider", ["anthropic", "openrouter_claude", "openrouter_other", "openai_compat", "responses", "ollama"])
def test_goal_reads_and_notifications_preserve_growing_prefix(provider):
    messages = [{"role": "system", "content": "Stable instructions"}, {"role": "user", "content": "Continue"},
        {"role": "assistant", "tool_calls": [{"id": "call_1", "function": {"name": "read_goal", "arguments": {}}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "Saved goal state"}]
    prefix = copy.deepcopy(messages)
    first = request(provider, messages)
    messages.extend([{"role": "assistant", "content": "Working"},
        {"role": "user", "content": f"{GOAL_STATE_PREFIX}\nThe goal changed since you last read it. "
                                    "Read it again before more goal work."}])
    second = request(provider, messages)
    assert messages[:len(prefix)] == prefix
    key = "input" if provider == "responses" else "messages"
    assert without_cache(first[key]) == without_cache(second[key][:len(first[key])])
    if provider == "anthropic":
        assert second["cache_control"] == {"type": "ephemeral"}
    elif provider == "openrouter_claude":
        assert second[key][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    else:
        assert "cache_control" not in json.dumps(second)


def test_direct_claude_uses_automatic_conversation_caching():
    kwargs = request("anthropic", [{"role": "user", "content": "Hello"}])
    assert kwargs["cache_control"] == {"type": "ephemeral"}


def test_openrouter_reports_cache_reads_and_writes():
    from types import SimpleNamespace
    from agent_core.providers._openai import _extract_usage

    usage = _extract_usage(SimpleNamespace(prompt_tokens=1200, completion_tokens=50,
        prompt_tokens_details=SimpleNamespace(cached_tokens=800, cache_write_tokens=300)))
    assert usage.cache_read_tokens == 800
    assert usage.cache_creation_tokens == 300
    assert usage.prompt_tokens == 1200


def test_empty_tool_result_never_becomes_an_empty_text_block():
    from agent_core.providers._prompt_cache import cache_conversation

    messages = [
        {"role": "user", "content": "Save the goal"},
        {"role": "assistant", "tool_calls": [{"id": "call_1", "function": {"name": "update_goal", "arguments": {}}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": ""},
    ]
    cache_conversation(messages)
    assert messages[-1]["content"] == ""
    assert {"type": "text", "text": ""} not in [block for message in messages
                                                if isinstance(message.get("content"), list)
                                                for block in message["content"]]
    # The cache marker moves to the last message that has a block.
    assert messages[0]["content"] == [{"type": "text", "text": "Save the goal", "cache_control": {"type": "ephemeral"}}]


def test_openrouter_claude_request_with_empty_tool_result_has_no_empty_text_block():
    messages = [
        {"role": "system", "content": "Stable instructions"}, {"role": "user", "content": "Save the goal"},
        {"role": "assistant", "tool_calls": [{"id": "call_1", "function": {"name": "update_goal", "arguments": {}}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": ""},
    ]
    kwargs = request("openrouter_claude", messages)
    serialized = json.dumps(kwargs["messages"])
    assert '{"type": "text", "text": ""' not in serialized
    assert "cache_control" in serialized
