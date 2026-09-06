"""Tests for provider API route helpers."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sdk.providers._models import ModelInfo
from server._provider_routes import _normalize_aperture_url, _sanitize, handle_add_provider

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


@pytest.mark.unit
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ai.example.ts.net", "http://ai.example.ts.net"),
        ("http://ai.example.ts.net:8080/", "http://ai.example.ts.net:8080"),
        ("http://ai.example.ts.net/ui/", "http://ai.example.ts.net"),
        ("http://ai.example.ts.net/ui/chat/providers", "http://ai.example.ts.net"),
        ("http://ai.example.ts.net/v1", "http://ai.example.ts.net"),
        ("http://ai.example.ts.net/v1/models", "http://ai.example.ts.net"),
        ("http://ai.example.ts.net/bedrock", "http://ai.example.ts.net"),
    ],
)
def test_normalize_aperture_url_accepts_common_gateway_forms(value: str, expected: str) -> None:
    assert _normalize_aperture_url(value) == expected


@pytest.mark.unit
def test_normalize_aperture_url_rejects_unknown_path() -> None:
    with pytest.raises(ValueError, match="gateway root"):
        _normalize_aperture_url("http://ai.example.ts.net/something-else")


@pytest.mark.unit
def test_normalize_aperture_url_rejects_embedded_credentials() -> None:
    with pytest.raises(ValueError, match="without embedded credentials"):
        _normalize_aperture_url("http://user:secret@ai.example.ts.net")


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
        patch("server._provider_routes.load_settings", return_value={"direct_providers": {}}),
        patch("server._provider_routes.save_settings") as save_settings,
        patch("server._provider_routes.get_provider", return_value=provider),
        patch("server._provider_routes.reset_provider"),
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

    response = await handle_add_provider(request)

    assert response.status == 400
    assert "Tailscale identity" in json.loads(response.body)["error"]
