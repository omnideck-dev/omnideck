"""Every wire format keeps runtime goal data after the cacheable conversation."""

import copy
import json

import pytest

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


@pytest.mark.parametrize("provider", ["anthropic", "openrouter_claude", "openrouter_other", "openai_compat", "responses", "ollama"])
@pytest.mark.parametrize("boundary", ["user", "tool"])
def test_runtime_updates_preserve_provider_prefix_and_do_not_leak_markers(provider, boundary):
    messages = [{"role": "system", "content": "Stable instructions"}, {"role": "user", "content": "Pursue my goal"}]
    if boundary == "tool":
        messages.extend([
            {"role": "assistant", "tool_calls": [{"id": "call_1", "function": {"name": "read_goal", "arguments": {}}}]},
            {"role": "tool", "tool_call_id": "call_1", "content": "Tool evidence"},
        ])
    prefix = copy.deepcopy(messages)
    messages.append({"role": "user", "content": "Goal revision 1", "_runtime_context": True})
    first = request(provider, messages)
    messages[-1]["content"] = "Goal revision 2"
    second = request(provider, messages)
    assert messages[:-1] == prefix  # conversion must not mutate the log or input dictionaries
    key = "input" if provider == "responses" else "messages"
    assert first[key][:-1] == second[key][:-1]
    assert first[key][-1] != second[key][-1]
    assert "_runtime_context" not in json.dumps(first)
    if provider in {"anthropic", "openrouter_claude"}:
        assert first[key][-2]["content"][-1]["cache_control"] == {"type": "ephemeral"}
        assert "cache_control" not in first[key][-1]
        assert "cache_control" not in first  # don't write an unusable cache at the transient tail
    else:
        assert "cache_control" not in json.dumps(first)


def test_direct_claude_keeps_automatic_caching_without_runtime_context():
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
