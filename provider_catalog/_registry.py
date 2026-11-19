"""Build and cache one client per connected provider."""

import logging
import os
from pathlib import Path

from config import load_config
from llm import ModelClient
from settings import load_settings

from ._catalog import provider_available, provider_entry
from ._fake import FakeClient

logger = logging.getLogger(__name__)

# When set, every provider name resolves to the in-process FakeClient so the
# app runs end-to-end without a real LLM backend (used by the e2e suite).
_MOCK_LLM_ENV = "MOCK_LLM"


def _mock_llm_enabled() -> bool:
    return os.environ.get(_MOCK_LLM_ENV, "").lower() in ("1", "true", "yes", "on")


_client_cache: dict[str, ModelClient] = {}


def _proxy_socket_path(provider_name: str) -> Path:
    """Return the broker socket path for the given provider.

    Brokered model providers are singletons — no suffix — so the connection ID
    is just ``llm_{provider}`` and the socket is ``llm_{provider}.sock``.
    """
    sockets_dir = Path(load_config().integrations.sockets_dir)
    return sockets_dir / f"llm_{provider_name}.sock"


def _create_client(provider_name: str) -> ModelClient:
    """Build the client for a connected provider.

    Direct providers are configured in ``settings.direct_providers`` and
    connect straight to their base URL. Everything else is a brokered
    model-provider connection reached through a Unix socket. A name with
    neither is not configured.
    """
    entry = provider_entry(provider_name)
    if not provider_available(provider_name):
        raise ValueError(f"Provider {provider_name!r} is turned off in Settings")

    direct = load_settings().get("direct_providers", {}).get(provider_name)
    if direct and direct.get("base_url"):
        client = entry.client(base_url=direct["base_url"])
        logger.info("Initialized LLM provider: %s (direct, %s)", provider_name, direct["base_url"])
        return client

    proxy_socket = _proxy_socket_path(provider_name)
    if proxy_socket.exists():
        client = entry.client(proxy_socket=proxy_socket)
        logger.info("Initialized LLM provider: %s (via broker at %s)", provider_name, proxy_socket)
        return client

    msg = f"Provider {provider_name!r} is not configured — add it on the Providers page"
    raise ValueError(msg)


def get_client(provider_name: str) -> ModelClient:
    """Return the cached client for a connected provider.

    Each provider name gets at most one cached client. It is created on first
    access and reused until ``reset_client()`` clears it.
    """
    cached = _client_cache.get(provider_name)
    if cached is not None:
        return cached
    client: ModelClient
    if _mock_llm_enabled():
        # The fake reports its models in the request format of the provider
        # it stands in for, so screens show that provider's real settings.
        client = FakeClient(inference_api=provider_entry(provider_name).inference_api)
        logger.info("Using FakeClient for %r (%s set)", provider_name, _MOCK_LLM_ENV)
    else:
        client = _create_client(provider_name)
    _client_cache[provider_name] = client
    return client


def reset_client(provider_name: str | None = None) -> None:
    """Clear cached client(s) so the next call re-creates them.

    Args:
        provider_name: Clear one provider's client, or all if None.
    """
    if provider_name is None:
        _client_cache.clear()
    else:
        _client_cache.pop(provider_name, None)


__all__ = ["get_client", "reset_client"]
