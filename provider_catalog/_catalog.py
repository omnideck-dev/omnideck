"""The providers a user can connect, and what each one needs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from llm import ModelClient
from settings import load_settings
from llm.clients import (
    AnthropicClient,
    ApertureClient,
    OllamaClient,
    OpenAIChatClient,
    OpenAIResponsesClient,
)

# Whether the add-provider form asks for a field, and whether it must be set.
FieldRule = Literal["required", "optional", "none"]


@dataclass(frozen=True)
class ProviderEntry:
    """One provider a user can connect."""

    name: str
    label: str
    description: str
    # Bootstrap Icons class the provider screens show.
    icon: str
    # The client class that talks to this provider.
    client: Callable[..., ModelClient]
    base_url: FieldRule
    api_key: FieldRule
    key_hint: str | None = None
    url_hint: str | None = None
    # A settings switch that must be on before this provider shows or runs.
    enabled_setting: str | None = None

    @property
    def inference_api(self) -> str | None:
        """The request format this provider speaks, or None if it varies per model."""
        value = getattr(self.client, "inference_api", None)
        return value if isinstance(value, str) else None


# Display order: local first, then the managed gateway, a generic
# compatibility option, and branded cloud APIs.
_ENTRIES = (
    ProviderEntry(
        name="ollama", label="Ollama", description="Run models on your own machine",
        icon="bi-cpu", client=OllamaClient, base_url="required", api_key="none",
    ),
    ProviderEntry(
        name="aperture", label="Tailscale Aperture",
        description="Discover models managed by your organization",
        icon="bi-diagram-3", client=ApertureClient, base_url="required", api_key="none",
        enabled_setting="aperture_enabled",
    ),
    ProviderEntry(
        name="openai_compat", label="OpenAI-compatible",
        description="vLLM, LM Studio, llama.cpp, etc.",
        icon="bi-hdd-network", client=OpenAIChatClient, base_url="required", api_key="optional",
        url_hint="http://localhost:1234/v1",
    ),
    ProviderEntry(
        name="anthropic", label="Anthropic", description="Claude models via API",
        icon="bi-cloud", client=AnthropicClient, base_url="none", api_key="required",
        key_hint="sk-ant-...",
    ),
    ProviderEntry(
        name="openai", label="OpenAI", description="GPT and o-series via API",
        icon="bi-cloud", client=OpenAIResponsesClient, base_url="none", api_key="required",
        key_hint="sk-...",
    ),
    ProviderEntry(
        name="openrouter", label="OpenRouter", description="Many providers, one API",
        icon="bi-router", client=OpenAIChatClient, base_url="none", api_key="required",
        key_hint="sk-or-v1-...",
    ),
)

PROVIDERS: dict[str, ProviderEntry] = {entry.name: entry for entry in _ENTRIES}


def provider_entry(name: str) -> ProviderEntry:
    """Return the catalog entry for *name*.

    Raises:
        ValueError: No provider has this name.
    """
    entry = PROVIDERS.get(name)
    if entry is None:
        raise ValueError(f"Unknown LLM provider: {name!r}. Available: {sorted(PROVIDERS)}")
    return entry


def provider_available(name: str) -> bool:
    """Whether *name* is a known provider whose settings switch, if any, is on."""
    entry = PROVIDERS.get(name)
    if entry is None:
        return False
    return entry.enabled_setting is None or load_settings().get(entry.enabled_setting) is True


def available_providers() -> list[ProviderEntry]:
    """Return the providers a user can connect right now, in display order."""
    return [entry for entry in _ENTRIES if provider_available(entry.name)]


def normalize_base_url(name: str, base_url: str) -> str:
    """Return *base_url* cleaned up the way the provider's client expects.

    Raises:
        ValueError: The provider cannot use this URL.
    """
    normalize = getattr(provider_entry(name).client, "normalize_base_url", None)
    return normalize(base_url) if normalize else base_url


__all__ = [
    "PROVIDERS",
    "FieldRule",
    "ProviderEntry",
    "available_providers",
    "normalize_base_url",
    "provider_available",
    "provider_entry",
]
