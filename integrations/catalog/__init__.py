"""Public catalog API shared by server routes and the supervisor.

Catalogs describe integration presets; they do not own configured connections,
credentials, or running brokers. Broker launch contracts live in
``integrations.drivers`` and operation definitions in ``integrations.operations``.
"""

from ._defaults import (
    DEFAULT_CATALOG,
    TEST_INTEGRATIONS_ENV,
    build_default_catalog,
    integration_catalog,
    model_provider_catalog,
    test_integrations_enabled,
)
from ._types import CatalogEntry, IntegrationCatalogEntry, ModelProviderCatalogEntry, OperationDisplayGroup
from ._validation import validate_catalog, validate_host_path_bindings

__all__ = [
    "CatalogEntry",
    "DEFAULT_CATALOG",
    "IntegrationCatalogEntry",
    "ModelProviderCatalogEntry",
    "OperationDisplayGroup",
    "TEST_INTEGRATIONS_ENV",
    "build_default_catalog",
    "integration_catalog",
    "model_provider_catalog",
    "test_integrations_enabled",
    "validate_catalog",
    "validate_host_path_bindings",
]
