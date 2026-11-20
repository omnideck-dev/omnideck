"""URL routing for API-key-backed model providers."""

import pytest

from brokering.brokers.llm_proxy._url import build_upstream_url


@pytest.mark.parametrize("base_path,provider,request_path,expected_path", [
    ("", "openai", "/v1/models", "/v1/models"),
    ("/v1", "openai", "/v1/models", "/v1/models"),
    ("/v1", "openai", "/v1/chat/completions", "/v1/chat/completions"),
    ("/v1", "openai", "/v1/responses", "/v1/responses"),
    ("/api", "openai", "/v1/models", "/api/v1/models"),
    ("/api/v1", "openai", "/v1/models?after=a%2Fb", "/api/v1/models?after=a%2Fb"),
    ("/v10", "openai", "/v1/models", "/v10/v1/models"),
    ("/v1/gateway", "openai", "/v1/models", "/v1/gateway/v1/models"),
    ("/v1", "openai", "/v10/models", "/v1/v10/models"),
    ("/v1", "openai", "/models", "/v1/models"),
    ("", "anthropic", "/v1/messages", "/v1/messages"),
    ("/v1", "anthropic", "/v1/messages", "/v1/v1/messages"),
])
def test_upstream_url(base_path, provider, request_path, expected_path):
    origin = "https://provider.example"
    assert build_upstream_url(
        origin + base_path, request_path, provider=provider,
    ) == origin + expected_path
