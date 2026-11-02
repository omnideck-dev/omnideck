"""Model-provider connection presets for the credential-injecting HTTP proxy.

These configure broker processes, not agent tools or model SDK adapters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from brokering.drivers import BrokerDriver


@dataclass(frozen=True)
class ModelProviderCatalogEntry:
    """An LLM-provider connection reusing the common broker platform."""

    slug: str
    title: str
    provider_protocol: Literal["openai", "anthropic"]
    driver: BrokerDriver
    driver_config: dict[str, str] = field(default_factory=dict)
    kind: Literal["model_provider"] = "model_provider"

    @property
    def driver_id(self) -> str:
        return self.driver.id

    def resolve_operations(self, granted_scopes: frozenset[str] = frozenset()) -> frozenset[str]:
        return frozenset()



_LLM_PROXY_DRIVER = BrokerDriver(
    id="model_provider.http_proxy",
    command=("python", "-m", "brokering.brokers.llm_proxy"),
    env_injection={"api_key": "LLM_API_KEY"},
)

_LLM_OPENAI_COMPAT_DRIVER = BrokerDriver(
    id="model_provider.openai_compatible_proxy",
    command=("python", "-m", "brokering.brokers.llm_proxy"),
    env_injection={"api_key": "LLM_API_KEY", "base_url": "LLM_BASE_URL"},
)


def _provider(
    slug: str,
    title: str,
    protocol: Literal["openai", "anthropic"],
    config: dict[str, str],
    *,
    driver: BrokerDriver = _LLM_PROXY_DRIVER,
) -> ModelProviderCatalogEntry:
    return ModelProviderCatalogEntry(
        slug=slug,
        title=title,
        provider_protocol=protocol,
        driver=driver,
        driver_config=config,
    )


_LLM_OPENAI = _provider(
    "llm_openai",
    "OpenAI API",
    "openai",
    {"LLM_PROVIDER": "openai", "LLM_BASE_URL": "https://api.openai.com"},
)
_LLM_ANTHROPIC = _provider(
    "llm_anthropic",
    "Anthropic API",
    "anthropic",
    {"LLM_PROVIDER": "anthropic", "LLM_BASE_URL": "https://api.anthropic.com"},
)
_LLM_OPENROUTER = _provider(
    "llm_openrouter",
    "OpenRouter",
    "openai",
    {"LLM_PROVIDER": "openai", "LLM_BASE_URL": "https://openrouter.ai/api"},
)
_LLM_OPENAI_COMPAT = _provider(
    "llm_openai_compat",
    "OpenAI-compatible",
    "openai",
    {"LLM_PROVIDER": "openai"},
    driver=_LLM_OPENAI_COMPAT_DRIVER,
)


_MODEL_PROVIDERS = (_LLM_OPENAI, _LLM_ANTHROPIC, _LLM_OPENROUTER, _LLM_OPENAI_COMPAT)


def model_provider_catalog() -> dict[str, ModelProviderCatalogEntry]:
    """Return the supported brokered model-provider connection presets."""
    return {entry.slug: entry for entry in _MODEL_PROVIDERS}
