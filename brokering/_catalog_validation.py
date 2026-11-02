"""Validate catalog definitions before starting broker processes."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import TYPE_CHECKING

from integrations.catalog import IntegrationCatalogEntry
from integrations.operations import OPERATIONS_BY_ID

if TYPE_CHECKING:
    from .catalog import CatalogEntry


def validate_host_path_bindings(
    catalog: Mapping[str, CatalogEntry],
    host_paths: Collection[str],
) -> None:
    """Fail fast if a driver references an unknown shared-directory role."""
    for slug, entry in catalog.items():
        for binding in entry.driver.host_paths:
            if binding.role not in host_paths:
                msg = f"catalog entry {slug!r} binds host-path role {binding.role!r} which is not in the registry"
                raise ValueError(msg)


def validate_catalog(catalog: Mapping[str, CatalogEntry]) -> None:
    """Fail fast on static catalog drift that would corrupt tool discovery."""
    for slug, entry in catalog.items():
        if slug != entry.slug:
            raise ValueError(
                f"catalog key {slug!r} does not match entry slug {entry.slug!r}",
            )
        if not entry.driver.command:
            raise ValueError(f"catalog entry {slug!r} has an empty broker command")
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in entry.driver_config.items()):
            raise ValueError(f"catalog entry {slug!r} has non-string driver config")
        if any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in entry.driver.env_injection.items()
        ):
            raise ValueError(f"catalog entry {slug!r} has invalid secret bindings")
        if not isinstance(entry, IntegrationCatalogEntry):
            continue

        declared = set(entry.operations)
        for operation_ids in entry.scope_operations.values():
            declared.update(operation_ids)
        unknown = declared.difference(OPERATIONS_BY_ID)
        if unknown:
            raise ValueError(
                f"catalog entry {slug!r} references unknown operations: {sorted(unknown)}",
            )

        group_ids = [group.id for group in entry.operation_groups]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError(f"catalog entry {slug!r} has duplicate operation group IDs")
        for group in entry.operation_groups:
            undeclared = group.operation_ids.difference(declared)
            if undeclared:
                raise ValueError(
                    f"catalog entry {slug!r} groups undeclared operations: {sorted(undeclared)}",
                )
