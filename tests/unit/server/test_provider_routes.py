"""Tests for provider API route helpers."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server._provider_routes import (
    _sanitize,
    handle_add_provider,
    handle_list_providers,
    handle_remove_provider,
    handle_update_provider,
)
from tools.integrations.types import RegisteredIntegration

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


# ── shared test doubles ──────────────────────────────────────────────────


def _request(body: dict | None = None, match: dict | None = None) -> MagicMock:
    req = MagicMock()
    req.json = AsyncMock(return_value=body or {})
    req.match_info = match or {}
    return req


class _FakeSettingsStore:
    """In-memory stand-in for settings.load_settings/save_settings."""

    def __init__(self, initial: dict | None = None):
        self._data = dict(initial or {})

    def load(self) -> dict:
        return dict(self._data)

    def save(self, patch_: dict) -> dict:
        self._data.update(patch_)
        return dict(self._data)


def _integration(integration_id: str, slug: str) -> RegisteredIntegration:
    return RegisteredIntegration(id=integration_id, slug=slug, permissions={}, state="running")


def _body(resp) -> dict:
    return json.loads(resp.body)


@pytest.mark.unit
class TestHandleAddProviderDirect:
    """POST /api/providers — direct (no api_key) providers."""

    @pytest.mark.asyncio
    async def test_failed_probe_does_not_persist(self):
        store = _FakeSettingsStore()
        with (
            patch("server._provider_routes.load_settings", side_effect=store.load),
            patch("server._provider_routes.save_settings", side_effect=store.save),
            patch(
                "server._provider_routes.probe_direct_provider",
                AsyncMock(side_effect=RuntimeError("connection refused")),
            ),
        ):
            resp = await handle_add_provider(_request({
                "name": "ollama",
                "base_url": "http://localhost:9999",
            }))

        assert resp.status == 503
        assert store.load().get("direct_providers", {}) == {}

    @pytest.mark.asyncio
    async def test_successful_probe_persists(self):
        store = _FakeSettingsStore()
        with (
            patch("server._provider_routes.load_settings", side_effect=store.load),
            patch("server._provider_routes.save_settings", side_effect=store.save),
            patch("server._provider_routes.probe_direct_provider", AsyncMock(return_value=[])),
            patch("server._provider_routes.reset_provider"),
        ):
            resp = await handle_add_provider(_request({
                "name": "ollama",
                "base_url": "http://localhost:11434",
            }))

        assert resp.status == 201
        assert store.load()["direct_providers"]["ollama"]["base_url"] == "http://localhost:11434"


@pytest.mark.unit
class TestHandleAddProviderBrokered:
    """POST /api/providers — brokered (api_key present) providers."""

    @pytest.mark.asyncio
    async def test_failed_probe_rolls_back_integration(self):
        store = _FakeSettingsStore()
        supervisor_calls: list[tuple[str, dict]] = []

        async def fake_supervisor_call(verb, args):
            supervisor_calls.append((verb, args))
            return {}

        added = _integration("llm_openai-id", "llm_openai")
        with (
            patch("server._provider_routes.load_settings", side_effect=store.load),
            patch("server._provider_routes.save_settings", side_effect=store.save),
            patch("server._provider_routes._supervisor_call", side_effect=fake_supervisor_call),
            patch("server._provider_routes.reset_provider"),
            patch(
                "server._provider_routes.get_provider",
                return_value=MagicMock(list_models=AsyncMock(side_effect=RuntimeError("401"))),
            ),
            patch("server._provider_routes.refresh_registered_integrations", AsyncMock()),
            patch(
                "server._provider_routes.registered_integrations",
                AsyncMock(return_value={"llm_openai-id": added}),
            ),
        ):
            resp = await handle_add_provider(_request({
                "name": "openai",
                "api_key": "sk-bad-key",
            }))

        assert resp.status == 503
        verbs = [verb for verb, _ in supervisor_calls]
        assert verbs == ["add", "remove"]
        assert supervisor_calls[1][1] == {"id": "llm_openai-id"}
        # A failed probe must not leave the display-only URL cache behind either.
        assert store.load().get("brokered_provider_urls", {}) == {}

    @pytest.mark.asyncio
    async def test_successful_probe_caches_base_url_for_display(self):
        store = _FakeSettingsStore()

        async def fake_supervisor_call(verb, args):
            return {}

        with (
            patch("server._provider_routes.load_settings", side_effect=store.load),
            patch("server._provider_routes.save_settings", side_effect=store.save),
            patch("server._provider_routes._supervisor_call", side_effect=fake_supervisor_call),
            patch("server._provider_routes.reset_provider"),
            patch(
                "server._provider_routes.get_provider",
                return_value=MagicMock(list_models=AsyncMock(return_value=[])),
            ),
        ):
            resp = await handle_add_provider(_request({
                "name": "openai_compat",
                "api_key": "sk-test",
                "base_url": "https://my-proxy.example.com/v1",
            }))

        assert resp.status == 201
        assert store.load()["brokered_provider_urls"]["openai_compat"] == (
            "https://my-proxy.example.com/v1"
        )

    @pytest.mark.asyncio
    async def test_blocked_host_rejected_before_touching_the_supervisor(self):
        store = _FakeSettingsStore()
        supervisor_calls: list[tuple[str, dict]] = []

        async def fake_supervisor_call(verb, args):
            supervisor_calls.append((verb, args))
            return {}

        with (
            patch("server._provider_routes.load_settings", side_effect=store.load),
            patch("server._provider_routes.save_settings", side_effect=store.save),
            patch("server._provider_routes._supervisor_call", side_effect=fake_supervisor_call),
        ):
            resp = await handle_add_provider(_request({
                "name": "openai_compat",
                "api_key": "sk-test",
                "base_url": "http://169.254.169.254/latest/meta-data/",
            }))

        assert resp.status == 400
        assert supervisor_calls == []
        assert store.load().get("brokered_provider_urls", {}) == {}


@pytest.mark.unit
class TestHandleListProviders:
    @pytest.mark.asyncio
    async def test_brokered_entry_includes_cached_base_url(self):
        store = _FakeSettingsStore({
            "brokered_provider_urls": {"openai_compat": "https://my-proxy.example.com/v1"},
        })
        integ = _integration("llm_openai_compat-id", "llm_openai_compat")
        with (
            patch("server._provider_routes.load_settings", side_effect=store.load),
            patch("server._provider_routes.refresh_registered_integrations", AsyncMock()),
            patch(
                "server._provider_routes.registered_integrations",
                AsyncMock(return_value={"llm_openai_compat-id": integ}),
            ),
        ):
            resp = await handle_list_providers(_request())

        providers = _body(resp)["providers"]
        assert providers[0]["name"] == "openai_compat"
        assert providers[0]["base_url"] == "https://my-proxy.example.com/v1"


@pytest.mark.unit
class TestHandleUpdateProviderBrokered:
    @pytest.mark.asyncio
    async def test_omitted_base_url_falls_back_to_stored_value(self):
        store = _FakeSettingsStore({
            "brokered_provider_urls": {"openai_compat": "https://old-proxy.example.com/v1"},
        })
        integ = _integration("llm_openai_compat-id", "llm_openai_compat")
        captured_add_args = {}

        async def fake_supervisor_call(verb, args):
            if verb == "add":
                captured_add_args.update(args)
            return {}

        with (
            patch("server._provider_routes.load_settings", side_effect=store.load),
            patch("server._provider_routes.save_settings", side_effect=store.save),
            patch(
                "server._provider_routes.registered_integrations",
                AsyncMock(return_value={"llm_openai_compat-id": integ}),
            ),
            patch("server._provider_routes._supervisor_call", side_effect=fake_supervisor_call),
            patch("server._provider_routes.reset_provider"),
            patch(
                "server._provider_routes.get_provider",
                return_value=MagicMock(list_models=AsyncMock(return_value=[])),
            ),
        ):
            resp = await handle_update_provider(
                _request({"api_key": "sk-new-key"}, match={"name": "openai_compat"}),
            )

        assert resp.status == 200
        assert captured_add_args["auth_blob"]["base_url"] == "https://old-proxy.example.com/v1"
        assert store.load()["brokered_provider_urls"]["openai_compat"] == (
            "https://old-proxy.example.com/v1"
        )

    @pytest.mark.asyncio
    async def test_blocked_host_rejected_without_touching_existing_integration(self):
        store = _FakeSettingsStore({
            "brokered_provider_urls": {"openai_compat": "https://old-proxy.example.com/v1"},
        })
        integ = _integration("llm_openai_compat-id", "llm_openai_compat")
        supervisor_calls: list[tuple[str, dict]] = []

        async def fake_supervisor_call(verb, args):
            supervisor_calls.append((verb, args))
            return {}

        with (
            patch("server._provider_routes.load_settings", side_effect=store.load),
            patch("server._provider_routes.save_settings", side_effect=store.save),
            patch(
                "server._provider_routes.registered_integrations",
                AsyncMock(return_value={"llm_openai_compat-id": integ}),
            ),
            patch("server._provider_routes._supervisor_call", side_effect=fake_supervisor_call),
        ):
            resp = await handle_update_provider(
                _request(
                    {"api_key": "sk-new-key", "base_url": "http://metadata.google.internal/"},
                    match={"name": "openai_compat"},
                ),
            )

        assert resp.status == 400
        assert supervisor_calls == []
        assert store.load()["brokered_provider_urls"]["openai_compat"] == (
            "https://old-proxy.example.com/v1"
        )


@pytest.mark.unit
class TestHandleRemoveProviderBrokered:
    @pytest.mark.asyncio
    async def test_clears_cached_base_url(self):
        store = _FakeSettingsStore({
            "brokered_provider_urls": {"openai_compat": "https://my-proxy.example.com/v1"},
        })
        integ = _integration("llm_openai_compat-id", "llm_openai_compat")

        async def fake_supervisor_call(verb, args):
            return {}

        with (
            patch("server._provider_routes.load_settings", side_effect=store.load),
            patch("server._provider_routes.save_settings", side_effect=store.save),
            patch(
                "server._provider_routes.registered_integrations",
                AsyncMock(return_value={"llm_openai_compat-id": integ}),
            ),
            patch("server._provider_routes._supervisor_call", side_effect=fake_supervisor_call),
            patch("server._provider_routes.reset_provider"),
        ):
            resp = await handle_remove_provider(_request(match={"name": "openai_compat"}))

        assert resp.status == 200
        assert store.load().get("brokered_provider_urls", {}) == {}
