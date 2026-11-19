"""The providers a user can connect, and the clients for connected ones."""

from ._catalog import (
    PROVIDERS,
    FieldRule,
    ProviderEntry,
    available_providers,
    normalize_base_url,
    provider_available,
    provider_entry,
)
from ._fake import FakeClient
from ._registry import get_client, reset_client

__all__ = [
    "PROVIDERS",
    "FakeClient",
    "FieldRule",
    "ProviderEntry",
    "available_providers",
    "get_client",
    "normalize_base_url",
    "provider_available",
    "provider_entry",
    "reset_client",
]
