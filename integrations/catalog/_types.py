"""Catalog domain types, independent of process lifecycle and persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from integrations.drivers import BrokerDriver


@dataclass(frozen=True)
class OperationDisplayGroup:
    """Optional catalog-owned grouping for presenting operation choices."""

    id: str
    title: str
    operation_ids: frozenset[str]


@dataclass(frozen=True)
class IntegrationCatalogEntry:
    """An installable integration preset backed by a broker driver."""

    slug: str
    title: str
    description: str
    category: str
    driver: BrokerDriver
    driver_config: dict[str, str] = field(default_factory=dict)
    operations: frozenset[str] = frozenset()
    scope_operations: dict[str, frozenset[str]] = field(default_factory=dict)
    operation_groups: tuple[OperationDisplayGroup, ...] = ()
    kind: Literal["integration"] = "integration"

    @property
    def driver_id(self) -> str:
        return self.driver.id

    def resolve_operations(self, auth_blob: dict | None = None) -> frozenset[str]:
        """Return operations available under this connection's remote auth."""
        if not self.scope_operations or auth_blob is None:
            return self.operations
        scopes_raw = auth_blob.get("scopes")
        if isinstance(scopes_raw, str):
            granted_scopes = set(scopes_raw.split())
        elif isinstance(scopes_raw, (list, tuple, set, frozenset)):
            granted_scopes = {scope for scope in scopes_raw if isinstance(scope, str)}
        else:
            granted_scopes = set()

        # ``operations`` are unconditionally available. Scope mappings add
        # operations authorized by remote OAuth grants, which lets future
        # catalog entries combine local and scope-dependent tools.
        available = set(self.operations)
        for scope, operation_ids in self.scope_operations.items():
            if scope in granted_scopes:
                available.update(operation_ids)
        return frozenset(available)


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

    def resolve_operations(self, _auth_blob: dict | None = None) -> frozenset[str]:
        return frozenset()


CatalogEntry: TypeAlias = IntegrationCatalogEntry | ModelProviderCatalogEntry
