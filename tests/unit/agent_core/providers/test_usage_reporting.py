"""Usage contracts tested with the installed provider SDKs, not only test doubles."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import json

import httpx
import pytest
from anthropic.types import Message
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from openai.types.completion_usage import CompletionUsage
from openai.types.responses.response_usage import ResponseUsage

from agent_core.events._models import AgentEvent, IterationPayload
from agent_core.providers._anthropic import AnthropicProvider, _normalize_response as normalize_anthropic
from agent_core.providers._models import ChatResponse, TokenUsage
from agent_core.providers._ollama import OllamaProvider, _UsageAsyncClient, _UsageChatResponse, _normalize_response as normalize_ollama
from agent_core.providers._openai import OpenAIProvider
from agent_core.providers._openai_responses import OpenAIResponsesProvider, _extract_usage as responses_usage
from agent_core.providers._openrouter import OpenRouterProvider


def openai_usage(**extra):
    return CompletionUsage.model_validate({
        "prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,
        "prompt_tokens_details": {"cached_tokens": 60, "cache_write_tokens": 10},
        **extra,
    })


def anthropic_message(**usage):
    return Message.model_validate({
        "id": "msg-test", "type": "message", "role": "assistant", "model": "test-model",
        "content": [{"type": "text", "text": "Hello"}], "stop_reason": "end_turn",
        "usage": {"input_tokens": 30, "output_tokens": 20, "cache_read_input_tokens": 60,
                  "cache_creation_input_tokens": 10,
                  "cache_creation": {"ephemeral_5m_input_tokens": 4, "ephemeral_1h_input_tokens": 6},
                  **usage},
    })


def test_anthropic_input_includes_cache_exactly_once_and_retains_ttl():
    usage = normalize_anthropic(anthropic_message()).usage
    assert usage == TokenUsage(prompt_tokens=100, completion_tokens=20, cache_read_tokens=60,
                               cache_creation_tokens=10, cache_creation_5m_tokens=4, cache_creation_1h_tokens=6)
    assert normalize_anthropic(SimpleNamespace(content=[], stop_reason=None, usage=None)).usage == TokenUsage()


@pytest.mark.parametrize("cost", [0, 0.00123, None])
def test_openrouter_cost_is_account_charge_not_upstream_cost(cost):
    raw = openai_usage(cost=cost, cost_details={"upstream_inference_cost": 99})
    usage = OpenRouterProvider._extract_usage(raw)
    assert usage == TokenUsage(prompt_tokens=100, completion_tokens=20, cache_read_tokens=60,
                               cache_creation_tokens=10, reported_cost_usd=cost)
    # Generic compatible servers have no established monetary-unit contract.
    assert OpenAIProvider._extract_usage(raw).reported_cost_usd is None


@pytest.mark.parametrize("extract", [OpenAIProvider._extract_usage, OpenRouterProvider._extract_usage, responses_usage])
def test_missing_usage_stays_unknown(extract):
    assert extract(None) == TokenUsage()


def test_responses_sdk_preserves_optional_cache_write_extension():
    raw = ResponseUsage.model_validate({"input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
                                       "input_tokens_details": {"cached_tokens": 60, "cache_write_tokens": 10},
                                       "output_tokens_details": {"reasoning_tokens": 5}})
    assert responses_usage(raw) == TokenUsage(prompt_tokens=100, completion_tokens=20,
                                             cache_read_tokens=60, cache_creation_tokens=10)


def test_ollama_sdk_preserves_cached_count_and_never_invents_cost():
    raw = _UsageChatResponse.model_validate({"message": {"role": "assistant", "content": "Hello"},
                                        "prompt_eval_count": 100, "eval_count": 20,
                                        "prompt_eval_cached_count": 60, "done": True})
    assert normalize_ollama(raw).usage == TokenUsage(prompt_tokens=100, completion_tokens=20, cache_read_tokens=60)


def test_zero_is_reported_and_unknown_does_not_become_a_complete_sdk_total():
    zero = OpenRouterProvider._extract_usage(openai_usage(prompt_tokens=0, completion_tokens=0, cost=0))
    assert zero.prompt_tokens == zero.completion_tokens == zero.reported_cost_usd == 0
    assert zero.combined_with(TokenUsage()) == TokenUsage()
    assert zero.combined_with(zero).reported_cost_usd == 0


def test_iteration_serialization_preserves_breakdown_and_legacy_replay():
    usage = normalize_anthropic(anthropic_message()).usage
    event = AgentEvent(payload=IterationPayload(type="iteration", iteration_index=0, usage=usage))
    flat = event.to_flat_dict("conv")
    assert flat["usage"] == usage.model_dump()
    assert flat["total_tokens"] is None
    assert IterationPayload.model_validate(flat).usage == usage
    assert IterationPayload(type="iteration", iteration_index=0, total_tokens=120).usage is None
    assert IterationPayload(type="iteration", iteration_index=0, stopped=True).usage is None


async def stream(items):
    for item in items:
        yield item


@pytest.mark.parametrize("provider_cls", [OpenAIProvider, OpenRouterProvider])
@pytest.mark.parametrize("streamed", [False, True])
async def test_chat_completion_paths_share_usage_normalization(provider_cls, streamed):
    raw = openai_usage(cost=0.0123)
    provider = provider_cls.__new__(provider_cls)
    provider._client = AsyncMock()
    if streamed:
        # The usage-only final chunk has NO choices. Losing it loses all usage.
        final = ChatCompletionChunk.model_validate({"id": "c", "created": 0, "model": "test-model",
                                                    "object": "chat.completion.chunk", "choices": [], "usage": raw})
        provider._client.chat.completions.create.return_value = stream([final])
        result = [item async for item in provider.chat_stream(model="test-model", messages=[])][-1]
    else:
        final = ChatCompletion.model_validate({"id": "c", "created": 0, "model": "test-model",
                                               "object": "chat.completion", "usage": raw,
                                               "choices": [{"index": 0, "finish_reason": "stop",
                                                            "message": {"role": "assistant", "content": "Hello"}}]})
        provider._client.chat.completions.create.return_value = final
        result = await provider.chat(model="test-model", messages=[])
    assert isinstance(result, ChatResponse)
    assert result.usage == provider_cls._extract_usage(raw)


async def test_anthropic_stream_uses_final_message_usage():
    raw = anthropic_message()
    provider = AnthropicProvider.__new__(AnthropicProvider)
    provider._client = MagicMock()
    fake_stream = MagicMock()
    fake_stream.__aiter__.return_value = []
    fake_stream.get_final_message = AsyncMock(return_value=raw)
    provider._client.messages.stream.return_value.__aenter__.return_value = fake_stream
    result = [item async for item in provider.chat_stream(model="test-model", messages=[])][-1]
    assert result.usage == normalize_anthropic(raw).usage


async def test_ollama_stream_uses_final_chunk_usage():
    raw = _UsageChatResponse.model_validate({"message": {"role": "assistant", "content": "Hello"}, "done": True,
                                        "prompt_eval_count": 100, "eval_count": 20, "prompt_eval_cached_count": 60})
    provider = OllamaProvider.__new__(OllamaProvider)
    provider._client = AsyncMock()
    provider._client.chat.return_value = stream([raw])
    result = [item async for item in provider.chat_stream(model="test-model", messages=[])][-1]
    assert result.usage == normalize_ollama(raw).usage
    assert result.usage.cache_read_tokens == 60


@pytest.mark.parametrize("streamed", [False, True])
@pytest.mark.parametrize("cached", [0, 60, None])
async def test_ollama_wire_decoding_preserves_optional_cache_counter(streamed, cached):
    payload = {"message": {"role": "assistant", "content": "Hello"}, "done": True,
               "prompt_eval_count": 100, "eval_count": 20}
    if cached is not None:
        payload["prompt_eval_cached_count"] = cached

    def respond(request):
        return httpx.Response(200, content=json.dumps(payload) + "\n", headers={"content-type": "application/x-ndjson"})

    client = _UsageAsyncClient(host="http://ollama.test", transport=httpx.MockTransport(respond))
    try:
        result = await client.chat(model="test-model", messages=[], stream=streamed)
        if streamed:
            result = [item async for item in result][-1]
        assert result.prompt_eval_cached_count == cached
        assert normalize_ollama(result).usage.cache_read_tokens == cached
    finally:
        await client._client.aclose()


async def test_responses_stream_uses_completed_event_usage():
    raw = SimpleNamespace(usage=ResponseUsage.model_validate({
        "input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
        "input_tokens_details": {"cached_tokens": 60}, "output_tokens_details": {"reasoning_tokens": 5},
    }), output=[], status="completed")
    provider = OpenAIResponsesProvider.__new__(OpenAIResponsesProvider)
    provider._client = AsyncMock()
    provider._client.responses.create.return_value = stream([SimpleNamespace(type="response.completed", response=raw)])
    result = [item async for item in provider.chat_stream(model="test-model", messages=[])][-1]
    assert result.usage == responses_usage(raw.usage)
