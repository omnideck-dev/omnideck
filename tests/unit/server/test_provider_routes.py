"""Tests for provider API route helpers."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sdk.providers._models import ModelInfo, ProviderError
from server._provider_routes import (
    _sanitize,
    handle_add_provider,
    handle_list_providers,
    handle_remove_provider,
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


def _make_request(body: dict | None = None, *, name: str | None = None) -> MagicMock:
    req = MagicMock()
    if body is not None:
        req.json = AsyncMock(return_value=body)
    if name is not None:
        req.match_info = {"name": name}
    return req


def _model(name: str = "m1") -> ModelInfo:
    return ModelInfo(name=name)


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
    models = [_model("llama")]

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
    assert data["models"][0]["name"] == "llama"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_brokered_does_not_create_when_probe_fails() -> None:
    body = {
        "name": "openai_compat",
        "base_url": "http://localhost:9999/v1",
        "api_key": "sk-test",
    }
    save = MagicMock()
    supervisor = AsyncMock()

    with (
        patch("server._provider_routes.load_settings", return_value={}),
        patch("server._provider_routes.save_settings", save),
        patch(
            "server._provider_routes._probe_models",
            new=AsyncMock(
                return_value=__import__("aiohttp").web.json_response(
                    {
                        "error": "provider_unreachable",
                        "message": "down",
                        "provider": "openai_compat",
                    },
                    status=503,
                ),
            ),
        ),
        patch("server._provider_routes._supervisor_call", new=supervisor),
    ):
        resp = await handle_add_provider(_make_request(body))

    assert resp.status == 503
    supervisor.assert_not_called()
    save.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_brokered_openai_compat_mirrors_base_url() -> None:
    body = {
        "name": "openai_compat",
        "base_url": "http://vllm:8000/v1",
        "api_key": "sk-test",
    }
    save = MagicMock()
    supervisor = AsyncMock(return_value={"id": "llm_openai_compat"})
    models = [_model("gpt")]

    with (
        patch("server._provider_routes.load_settings", return_value={"brokered_base_urls": {}}),
        patch("server._provider_routes.save_settings", save),
        patch("server._provider_routes._probe_models", new=AsyncMock(return_value=models)),
        patch("server._provider_routes._supervisor_call", new=supervisor),
        patch("server._provider_routes.reset_provider"),
    ):
        resp = await handle_add_provider(_make_request(body))

    assert resp.status == 201
    supervisor.assert_awaited_once()
    add_args = supervisor.await_args.args[1]
    assert add_args["auth_blob"] == {
        "api_key": "sk-test",
        "base_url": "http://vllm:8000/v1",
    }
    # Non-secret mirror so GET/edit can show the URL.
    assert any(
        call.args[0] == {"brokered_base_urls": {"openai_compat": "http://vllm:8000/v1"}}
        for call in save.call_args_list
    )
    data = json.loads(resp.body)
    assert data["provider"]["kind"] == "brokered"
    assert data["provider"]["base_url"] == "http://vllm:8000/v1"


# ── handle_list_providers ────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_includes_brokered_base_url_mirror() -> None:
    settings = {
        "direct_providers": {"ollama": {"base_url": "http://localhost:11434"}},
        "brokered_base_urls": {"openai_compat": "http://vllm:8000/v1"},
    }
    ri = SimpleNamespace(slug="llm_openai_compat", state="running")

    with (
        patch("server._provider_routes.load_settings", return_value=settings),
        patch(
            "server._provider_routes.refresh_registered_integrations",
            new=AsyncMock(),
        ),
        patch(
            "server._provider_routes.registered_integrations",
            new=AsyncMock(return_value={"llm_openai_compat": ri}),
        ),
    ):
        resp = await handle_list_providers(MagicMock())

    assert resp.status == 200
    data = json.loads(resp.body)
    by_name = {p["name"]: p for p in data["providers"]}
    assert by_name["ollama"]["base_url"] == "http://localhost:11434"
    assert by_name["openai_compat"]["kind"] == "brokered"
    assert by_name["openai_compat"]["base_url"] == "http://vllm:8000/v1"


# ── handle_update_provider ───────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_direct_does_not_persist_when_probe_fails() -> None:
    settings = {"direct_providers": {"ollama": {"base_url": "http://localhost:11434"}}}
    save = MagicMock()

    with (
        patch("server._provider_routes.load_settings", return_value=settings),
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
    ):
        resp = await handle_update_provider(
            _make_request({"base_url": "http://localhost:1"}, name="ollama"),
        )

    assert resp.status == 503
    save.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_brokered_sends_base_url_in_auth_blob() -> None:
    settings = {"brokered_base_urls": {"openai_compat": "http://old:8000/v1"}}
    ri = SimpleNamespace(id="llm_openai_compat", slug="llm_openai_compat")
    supervisor = AsyncMock()
    save = MagicMock()
    models = [_model()]

    with (
        patch("server._provider_routes.load_settings", return_value=settings),
        patch("server._provider_routes.save_settings", save),
        patch(
            "server._provider_routes.registered_integrations",
            new=AsyncMock(return_value={"llm_openai_compat": ri}),
        ),
        patch("server._provider_routes._probe_models", new=AsyncMock(return_value=models)),
        patch("server._provider_routes._supervisor_call", new=supervisor),
        patch("server._provider_routes.reset_provider"),
    ):
        resp = await handle_update_provider(
            _make_request(
                {"api_key": "sk-new", "base_url": "http://new:8000/v1"},
                name="openai_compat",
            ),
        )

    assert resp.status == 200
    # remove then add
    assert supervisor.await_count == 2
    add_call = supervisor.await_args_list[1]
    assert add_call.args[0] == "add"
    assert add_call.args[1]["auth_blob"] == {
        "api_key": "sk-new",
        "base_url": "http://new:8000/v1",
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_remove_clears_brokered_base_url_mirror() -> None:
    settings = {"direct_providers": {}, "brokered_base_urls": {"openai_compat": "http://x"}}
    ri = SimpleNamespace(id="llm_openai_compat", slug="llm_openai_compat")
    save = MagicMock()

    with (
        patch("server._provider_routes.load_settings", return_value=settings),
        patch("server._provider_routes.save_settings", save),
        patch(
            "server._provider_routes.registered_integrations",
            new=AsyncMock(return_value={"x": ri}),
        ),
        patch("server._provider_routes._supervisor_call", new=AsyncMock()),
        patch("server._provider_routes.reset_provider"),
    ):
        resp = await handle_remove_provider(_make_request(name="openai_compat"))

    assert resp.status == 200
    assert any(
        call.args[0] == {"brokered_base_urls": {}}
        for call in save.call_args_list
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_probe_error_from_provider_error() -> None:
    """Ephemeral list_models ProviderError becomes 503 without persisting."""
    body = {"name": "ollama", "base_url": "http://localhost:11434"}
    save = MagicMock()

    class Boom:
        async def list_models(self):
            raise ProviderError("connection refused")

    with (
        patch("server._provider_routes.load_settings", return_value={"direct_providers": {}}),
        patch("server._provider_routes.save_settings", save),
        patch("server._provider_routes._ephemeral_provider", return_value=Boom()),
    ):
        resp = await handle_add_provider(_make_request(body))

    assert resp.status == 503
    data = json.loads(resp.body)
    assert data["error"] == "provider_unreachable"
    save.assert_not_called()
