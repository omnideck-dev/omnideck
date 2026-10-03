"""Tests for provider API route helpers."""

from __future__ import annotations

import json

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server._provider_routes import (
    _brokered_provider_connections,
    _sanitize,
    handle_add_provider,
    handle_list_providers,
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
    monkeypatch.setattr("server._provider_routes.get_provider", lambda _name: _Provider())
    monkeypatch.setattr("server._provider_routes.reset_provider", lambda _name: None)
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
    monkeypatch.setattr("server._provider_routes.get_provider", lambda _name: _Provider())
    monkeypatch.setattr("server._provider_routes.reset_provider", lambda _name: None)
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


def _make_request(body: dict | None = None, *, name: str | None = None) -> MagicMock:
    req = MagicMock()
    if body is not None:
        req.json = AsyncMock(return_value=body)
    if name is not None:
        req.match_info = {"name": name}
    return req


# ── handle_add_provider — probe before persist ───────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_direct_does_not_persist_when_probe_fails() -> None:
    """Failed Test & add must leave settings untouched."""
    body = {"name": "ollama", "base_url": "http://localhost:9999"}
    save = MagicMock()

    with (
        patch("server._provider_routes.load_settings", return_value={"direct_providers": {}}),
        patch("server._provider_routes.save_settings", save),
        patch(
            "server._provider_routes._probe_models",
            new=AsyncMock(
                return_value=__import__("aiohttp").web.json_response(
                    {"error": "provider_unreachable", "message": "down", "provider": "ollama"},
                    status=503,
                ),
            ),
        ),
        patch("server._provider_routes._supervisor_call", new=AsyncMock()) as supervisor,
    ):
        resp = await handle_add_provider(_make_request(body))

    assert resp.status == 503
    save.assert_not_called()
    supervisor.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_direct_persists_only_after_successful_probe() -> None:
    body = {"name": "ollama", "base_url": "http://localhost:11434"}
    save = MagicMock()
    models = [SimpleNamespace(model_dump=lambda: {"id": "llama"})]

    with (
        patch("server._provider_routes.load_settings", return_value={"direct_providers": {}}),
        patch("server._provider_routes.save_settings", save),
        patch("server._provider_routes._probe_models", new=AsyncMock(return_value=models)),
        patch("server._provider_routes.reset_provider") as reset,
    ):
        resp = await handle_add_provider(_make_request(body))

    assert resp.status == 201
    save.assert_called_once_with(
        {"direct_providers": {"ollama": {"base_url": "http://localhost:11434"}}},
    )
    reset.assert_called_once_with("ollama")
    data = json.loads(resp.body)
    assert data["provider"]["name"] == "ollama"
    assert data["provider"]["kind"] == "direct"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_brokered_does_not_call_supervisor_when_probe_fails() -> None:
    body = {"name": "openai", "api_key": "sk-test"}
    save = MagicMock()
    supervisor = AsyncMock()

    with (
        patch("server._provider_routes.load_settings", return_value={"direct_providers": {}}),
        patch("server._provider_routes.save_settings", save),
        patch(
            "server._provider_routes._probe_models",
            new=AsyncMock(
                return_value=__import__("aiohttp").web.json_response(
                    {"error": "provider_unreachable", "message": "down", "provider": "openai"},
                    status=503,
                ),
            ),
        ),
        patch("server._provider_routes._supervisor_call", supervisor),
    ):
        resp = await handle_add_provider(_make_request(body))

    assert resp.status == 503
    supervisor.assert_not_called()
    save.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_direct_does_not_persist_when_probe_fails(monkeypatch) -> None:
    body = {"base_url": "http://localhost:9999"}
    save = MagicMock()

    monkeypatch.setattr(
        "server._provider_routes.load_settings",
        lambda: {"direct_providers": {"ollama": {"base_url": "http://localhost:11434"}}},
    )
    monkeypatch.setattr("server._provider_routes.save_settings", save)
    monkeypatch.setattr(
        "server._provider_routes._probe_models",
        AsyncMock(
            return_value=__import__("aiohttp").web.json_response(
                {"error": "provider_unreachable", "message": "down", "provider": "ollama"},
                status=503,
            ),
        ),
    )

    resp = await handle_update_provider(_make_request(body, name="ollama"))
    assert resp.status == 503
    save.assert_not_called()
