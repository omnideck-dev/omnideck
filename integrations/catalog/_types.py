"""Catalog domain types, independent of process lifecycle and persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from brokering.drivers import BrokerDriver


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

    def resolve_operations(self, granted_scopes: frozenset[str] = frozenset()) -> frozenset[str]:
        """Resolve availability using scope metadata only, never credentials."""
        # ``operations`` are unconditionally available. Scope mappings add
        # operations authorized by remote OAuth grants, which lets future
        # catalog entries combine local and scope-dependent tools.
        available = set(self.operations)
        for scope, operation_ids in self.scope_operations.items():
            if scope in granted_scopes:
                available.update(operation_ids)
        return frozenset(available)
