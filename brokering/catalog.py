"""Compose the process catalog consumed by the supervisor.

This is an application composition boundary: it brings together tool-integration
presets and model-provider proxy presets. Transport and process primitives do
not load this catalog. The supervisor still owns the existing domain-specific
connection policy; this package move does not introduce a generic policy engine.
"""

from __future__ import annotations

from typing import TypeAlias

from integrations.catalog import IntegrationCatalogEntry, build_integration_catalog

from ._catalog_validation import validate_catalog, validate_host_path_bindings
from .brokers.llm_proxy.catalog import ModelProviderCatalogEntry, model_provider_catalog

CatalogEntry: TypeAlias = IntegrationCatalogEntry | ModelProviderCatalogEntry


def build_default_catalog(*, include_test_integrations: bool | None = None) -> dict[str, CatalogEntry]:
    """Build both connection catalogs, preserving the development-only gate."""
    return {
        **build_integration_catalog(include_test_integrations=include_test_integrations),
        **model_provider_catalog(),
    }


DEFAULT_CATALOG = build_default_catalog()

__all__ = [
    "CatalogEntry",
    "DEFAULT_CATALOG",
    "build_default_catalog",
    "validate_catalog",
    "validate_host_path_bindings",
]
