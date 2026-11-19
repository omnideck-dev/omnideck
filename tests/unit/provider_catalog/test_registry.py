"""Tests for the provider registry and get_client factory."""

from unittest.mock import MagicMock, patch

import pytest

from provider_catalog._registry import _proxy_socket_path, get_client, reset_client


@pytest.fixture(autouse=True)
def _clean_provider():
    """Ensure provider cache is cleared before and after each test."""
    reset_client()
    yield
    reset_client()


def _fake_config(sockets_dir="/tmp/no-such-dir-in-tests"):
    cfg = MagicMock()
    cfg.integrations.sockets_dir = sockets_dir
    return cfg


def _direct(name, base_url):
    return {"direct_providers": {name: {"base_url": base_url}}}


@pytest.mark.unit
class TestGetProvider:
    def test_returns_direct_ollama_provider(self):
        """Ollama configured as a direct provider → direct connection."""
        with patch("provider_catalog._registry.load_settings", return_value=_direct("ollama", "http://localhost:11434")), \
             patch("provider_catalog._registry.load_config", return_value=_fake_config()):
            provider = get_client("ollama")
        from llm.clients._ollama import OllamaClient
        assert isinstance(provider, OllamaClient)

    def test_caches_by_name(self):
        with patch("provider_catalog._registry.load_settings", return_value=_direct("ollama", "http://localhost:11434")), \
             patch("provider_catalog._registry.load_config", return_value=_fake_config()):
            p1 = get_client("ollama")
            p2 = get_client("ollama")
        assert p1 is p2

    def test_reset_clears_one(self):
        with patch("provider_catalog._registry.load_settings", return_value=_direct("ollama", "http://localhost:11434")), \
             patch("provider_catalog._registry.load_config", return_value=_fake_config()):
            p1 = get_client("ollama")
            reset_client("ollama")
            p2 = get_client("ollama")
        assert p1 is not p2

    def test_reset_clears_all(self):
        with patch("provider_catalog._registry.load_settings", return_value=_direct("ollama", "http://localhost:11434")), \
             patch("provider_catalog._registry.load_config", return_value=_fake_config()):
            p1 = get_client("ollama")
            reset_client()
            p2 = get_client("ollama")
        assert p1 is not p2

    def test_unknown_provider_raises(self):
        with patch("provider_catalog._registry.load_settings", return_value={}), \
             patch("provider_catalog._registry.load_config", return_value=_fake_config()):
            with pytest.raises(ValueError, match="Unknown LLM provider"):
                get_client("unknown")

    def test_direct_with_base_url(self):
        """A direct provider entry connects straight to its base URL."""
        with patch("provider_catalog._registry.load_settings", return_value=_direct("openai", "http://lm-studio:1234/v1")), \
             patch("provider_catalog._registry.load_config", return_value=_fake_config()):
            provider = get_client("openai")
        from llm.clients._openai_responses import OpenAIResponsesClient
        assert isinstance(provider, OpenAIResponsesClient)
        assert "lm-studio" in str(provider._client.base_url)

    def test_brokered_via_socket(self, tmp_path):
        """No direct entry but a broker socket exists → connect through it."""
        (tmp_path / "llm_openai.sock").touch()
        with patch("provider_catalog._registry.load_settings", return_value={}), \
             patch("provider_catalog._registry.load_config", return_value=_fake_config(str(tmp_path))):
            provider = get_client("openai")
        from llm.clients._openai_responses import OpenAIResponsesClient
        assert isinstance(provider, OpenAIResponsesClient)
        assert provider._client.base_url.host == "localhost"

    def test_brokered_anthropic_via_socket(self, tmp_path):
        (tmp_path / "llm_anthropic.sock").touch()
        with patch("provider_catalog._registry.load_settings", return_value={}), \
             patch("provider_catalog._registry.load_config", return_value=_fake_config(str(tmp_path))):
            provider = get_client("anthropic")
        from llm.clients._anthropic import AnthropicClient
        assert isinstance(provider, AnthropicClient)

    def test_openai_compat_uses_openai_provider(self, tmp_path):
        """openai_compat maps to the same OpenAIChatClient class."""
        (tmp_path / "llm_openai_compat.sock").touch()
        with patch("provider_catalog._registry.load_settings", return_value={}), \
             patch("provider_catalog._registry.load_config", return_value=_fake_config(str(tmp_path))):
            provider = get_client("openai_compat")
        from llm.clients._openai_chat import OpenAIChatClient
        assert isinstance(provider, OpenAIChatClient)

    def test_openrouter_uses_openai_provider(self, tmp_path):
        """openrouter maps to OpenAIChatClient (OpenAI-compatible API)."""
        (tmp_path / "llm_openrouter.sock").touch()
        with patch("provider_catalog._registry.load_settings", return_value={}), \
             patch("provider_catalog._registry.load_config", return_value=_fake_config(str(tmp_path))):
            provider = get_client("openrouter")
        from llm.clients._openai_chat import OpenAIChatClient
        assert isinstance(provider, OpenAIChatClient)

    def test_aperture_uses_gateway_provider(self):
        settings = {**_direct("aperture", "http://ai.example.ts.net"), "aperture_enabled": True}
        with patch("provider_catalog._registry.load_settings", return_value=settings), \
             patch("provider_catalog._catalog.load_settings", return_value=settings), \
             patch("provider_catalog._registry.load_config", return_value=_fake_config()):
            provider = get_client("aperture")
        from llm.clients._aperture import ApertureClient
        assert isinstance(provider, ApertureClient)
        assert provider._gateway_url == "http://ai.example.ts.net"

    def test_aperture_is_refused_while_its_switch_is_off(self):
        settings = _direct("aperture", "http://ai.example.ts.net")
        with patch("provider_catalog._registry.load_settings", return_value=settings), \
             patch("provider_catalog._catalog.load_settings", return_value=settings), \
             patch("provider_catalog._registry.load_config", return_value=_fake_config()):
            with pytest.raises(ValueError, match="turned off"):
                get_client("aperture")

    def test_not_configured_raises(self):
        """A provider with no direct entry and no broker socket gives a clear error."""
        with patch("provider_catalog._registry.load_settings", return_value={}), \
             patch("provider_catalog._registry.load_config", return_value=_fake_config()):
            with pytest.raises(ValueError, match="not configured"):
                get_client("anthropic")


@pytest.mark.unit
class TestProxySocketPath:
    """_proxy_socket_path derives socket path from provider name."""

    def test_openai(self, tmp_path):
        with patch("provider_catalog._registry.load_config", return_value=_fake_config(str(tmp_path))):
            result = _proxy_socket_path("openai")
        assert result == tmp_path / "llm_openai.sock"

    def test_anthropic(self, tmp_path):
        with patch("provider_catalog._registry.load_config", return_value=_fake_config(str(tmp_path))):
            result = _proxy_socket_path("anthropic")
        assert result == tmp_path / "llm_anthropic.sock"

    def test_openai_compat(self, tmp_path):
        with patch("provider_catalog._registry.load_config", return_value=_fake_config(str(tmp_path))):
            result = _proxy_socket_path("openai_compat")
        assert result == tmp_path / "llm_openai_compat.sock"

    def test_openrouter(self, tmp_path):
        with patch("provider_catalog._registry.load_config", return_value=_fake_config(str(tmp_path))):
            result = _proxy_socket_path("openrouter")
        assert result == tmp_path / "llm_openrouter.sock"

    def test_aperture(self, tmp_path):
        with patch("provider_catalog._registry.load_config", return_value=_fake_config(str(tmp_path))):
            result = _proxy_socket_path("aperture")
        assert result == tmp_path / "llm_aperture.sock"
