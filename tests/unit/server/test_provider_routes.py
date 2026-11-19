"""Tests for provider API route helpers."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm import ModelInfo
from server._provider_routes import (
    _brokered_provider_connections,
    _sanitize,
    handle_add_provider,
    handle_list_providers,
    handle_provider_catalog,
    handle_update_provider,
)

# A wrong URL that lands on a reverse proxy returns an HTML error page; the
# client hands the whole page back as the error string.
_NGINX_404 = (
    "<html>\r\n<head><title>404 Not Found</title></head>\r\n<body>\r\n"
    "<center><h1>404 Not Found</h1></center>\r\n"
    "<hr><center>nginx/1.24.0 (Ubuntu)</center>\r\n</body>\r\n</html>\r\n"
    " (status code: 404)"
)


@pytest.mark.unit
def test_sanitize_collapses_html_page_and_keeps_status() -> None:
    out = _sanitize(_NGINX_404)

    assert "<" not in out
    assert "nginx" not in out
    assert out == "The server returned an unexpected response (HTTP 404)."


@pytest.mark.unit
def test_sanitize_collapses_html_without_status_code() -> None:
    out = _sanitize("<html><body>Bad Gateway</body></html>")

    assert out == "The server returned an unexpected response."


@pytest.mark.unit
def test_sanitize_passes_through_plain_messages() -> None:
    msg = "Connection refused"

    assert _sanitize(msg) == msg


@pytest.mark.unit
def test_sanitize_still_scrubs_credentials() -> None:
    out = _sanitize("auth failed for sk-abcdef0123456789 using Bearer sometoken")

    assert "sk-abcdef0123456789" not in out
    assert "sk-***" in out
    assert "Bearer ***" in out


@pytest.mark.asyncio
async def test_provider_domain_list_uses_kind_discriminator(monkeypatch) -> None:
    async def _call(verb, args):
        assert verb == "list"
        assert args == {"kind": "model_provider"}
        return {"connections": [{"id": "llm_openai", "kind": "model_provider"}]}

    monkeypatch.setattr("server._provider_routes._supervisor_call", _call)
    assert await _brokered_provider_connections() == [
        {"id": "llm_openai", "kind": "model_provider"},
    ]


@pytest.mark.asyncio
async def test_brokered_provider_add_has_no_integration_permissions(monkeypatch) -> None:
    captured = {}

    async def _supervisor(verb, args):
        captured.update(args)
        return {"id": "llm_openai", "kind": "model_provider"}

    class _Provider:
        async def list_models(self):
            return [SimpleNamespace(model_dump=lambda: {"id": "gpt-test"})]

    monkeypatch.setattr("server._provider_routes._supervisor_call", _supervisor)
    monkeypatch.setattr("server._provider_routes.get_client", lambda _name: _Provider())
    monkeypatch.setattr("server._provider_routes.reset_client", lambda _name: None)
    request = MagicMock()
    request.json = AsyncMock(return_value={"name": "openai", "api_key": "sk-test"})

    response = await handle_add_provider(request)
    assert response.status == 201
    assert captured["kind"] == "model_provider"
    assert "permissions" not in captured
    assert "operation_grants" not in captured


@pytest.mark.asyncio
async def test_provider_list_keeps_direct_providers_when_supervisor_is_down(monkeypatch) -> None:
    async def _unavailable():
        raise FileNotFoundError("supervisor down")

    monkeypatch.setattr("server._provider_routes._brokered_provider_connections", _unavailable)
    monkeypatch.setattr(
        "server._provider_routes.load_settings",
        lambda: {"direct_providers": {"ollama": {"base_url": "http://localhost:11434"}}},
    )

    response = await handle_list_providers(MagicMock())
    body = response.body.decode()
    assert response.status == 200
    assert '"name": "ollama"' in body
    assert '"brokered_available": false' in body


@pytest.mark.asyncio
async def test_brokered_provider_update_uses_transactional_reconnect(monkeypatch) -> None:
    calls = []

    async def _supervisor(verb, args):
        calls.append((verb, args))
        if verb == "list":
            return {
                "connections": [{
                    "id": "llm_openai",
                    "slug": "llm_openai",
                    "kind": "model_provider",
                }],
            }
        assert verb == "reconnect"
        return {"id": "llm_openai", "kind": "model_provider"}

    class _Provider:
        async def list_models(self):
            return [SimpleNamespace(model_dump=lambda: {"id": "gpt-test"})]

    monkeypatch.setattr("server._provider_routes._supervisor_call", _supervisor)
    monkeypatch.setattr("server._provider_routes.load_settings", lambda: {})
    monkeypatch.setattr("server._provider_routes.get_client", lambda _name: _Provider())
    monkeypatch.setattr("server._provider_routes.reset_client", lambda _name: None)
    request = MagicMock()
    request.match_info = {"name": "openai"}
    request.json = AsyncMock(return_value={"api_key": "sk-new"})

    response = await handle_update_provider(request)
    assert response.status == 200
    assert calls[-1] == (
        "reconnect",
        {
            "id": "llm_openai",
            "kind": "model_provider",
            "auth_blob": {"api_key": "sk-new"},
        },
    )
    assert all(verb != "remove" for verb, _args in calls)


@pytest.mark.unit
async def test_add_aperture_normalizes_and_stores_a_direct_provider() -> None:
    request = MagicMock()
    request.json = AsyncMock(return_value={
        "name": "aperture",
        "base_url": "ai.example.ts.net/ui/chat",
    })
    provider = MagicMock()
    provider.list_models = AsyncMock(return_value=[ModelInfo(name="bedrock/claude")])

    with (
        patch("provider_catalog._catalog.load_settings", return_value={"aperture_enabled": True}),
        patch("server._provider_routes.load_settings", return_value={"direct_providers": {}}),
        patch("server._provider_routes.save_settings") as save_settings,
        patch("server._provider_routes.get_client", return_value=provider),
        patch("server._provider_routes.reset_client"),
    ):
        response = await handle_add_provider(request)

    assert response.status == 201
    assert json.loads(response.body)["provider"]["base_url"] == "http://ai.example.ts.net"
    save_settings.assert_called_once_with({
        "direct_providers": {
            "aperture": {"base_url": "http://ai.example.ts.net"},
        }
    })


@pytest.mark.unit
async def test_add_aperture_rejects_api_keys() -> None:
    request = MagicMock()
    request.json = AsyncMock(return_value={
        "name": "aperture",
        "base_url": "http://ai.example.ts.net",
        "api_key": "not-needed",
    })

    with patch("provider_catalog._catalog.load_settings", return_value={"aperture_enabled": True}):
        response = await handle_add_provider(request)

    assert response.status == 400
    assert "does not use an API key" in json.loads(response.body)["error"]


@pytest.mark.unit
async def test_add_aperture_is_refused_until_the_experiment_is_on() -> None:
    request = MagicMock()
    request.json = AsyncMock(return_value={
        "name": "aperture",
        "base_url": "http://ai.example.ts.net",
    })

    with (
        patch("provider_catalog._catalog.load_settings", return_value={"aperture_enabled": False}),
        patch("server._provider_routes.save_settings") as save_settings,
    ):
        response = await handle_add_provider(request)

    assert response.status == 403
    assert "Experimental" in json.loads(response.body)["error"]
    save_settings.assert_not_called()


@pytest.mark.unit
async def test_update_aperture_is_refused_until_the_experiment_is_on() -> None:
    request = MagicMock()
    request.match_info = {"name": "aperture"}
    request.json = AsyncMock(return_value={"base_url": "http://ai.example.ts.net"})

    with (
        patch("provider_catalog._catalog.load_settings", return_value={"aperture_enabled": False}),
        patch("server._provider_routes.save_settings") as save_settings,
    ):
        response = await handle_update_provider(request)

    assert response.status == 403
    save_settings.assert_not_called()


@pytest.mark.unit
@pytest.mark.parametrize(("enabled", "expected"), [(False, ["ollama"]), (True, ["ollama", "aperture"])])
async def test_provider_list_shows_aperture_only_when_the_experiment_is_on(
    enabled: bool, expected: list[str],
) -> None:
    settings = {
        "direct_providers": {
            "ollama": {"base_url": "http://localhost:11434"},
            "aperture": {"base_url": "http://ai.example.ts.net"},
        },
    }

    with (
        patch("provider_catalog._catalog.load_settings", return_value={"aperture_enabled": enabled}),
        patch("server._provider_routes.load_settings", return_value=settings),
        patch("server._provider_routes._brokered_provider_connections", new=AsyncMock(return_value=[])),
    ):
        response = await handle_list_providers(MagicMock())

    assert [provider["name"] for provider in json.loads(response.body)["providers"]] == expected


@pytest.mark.unit
@pytest.mark.parametrize("enabled", [False, True])
async def test_catalog_lists_connectable_providers_in_display_order(enabled: bool) -> None:
    with patch("provider_catalog._catalog.load_settings", return_value={"aperture_enabled": enabled}):
        response = await handle_provider_catalog(MagicMock())

    providers = json.loads(response.body)["providers"]
    expected = ["ollama", "openai_compat", "anthropic", "openai", "openrouter"]
    if enabled:
        expected.insert(1, "aperture")
    assert [provider["name"] for provider in providers] == expected
    anthropic = next(provider for provider in providers if provider["name"] == "anthropic")
    assert anthropic == {
        "name": "anthropic",
        "label": "Anthropic",
        "description": "Claude models via API",
        "icon": "bi-cloud",
        "base_url": "none",
        "api_key": "required",
        "key_hint": "sk-ant-...",
        "url_hint": None,
    }


@pytest.mark.unit
async def test_add_rejects_a_key_for_providers_that_take_none() -> None:
    request = MagicMock()
    request.json = AsyncMock(return_value={
        "name": "ollama",
        "base_url": "http://localhost:11434",
        "api_key": "not-needed",
    })

    response = await handle_add_provider(request)

    assert response.status == 400
    assert json.loads(response.body)["error"] == "Ollama does not use an API key"
