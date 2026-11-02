"""Broker-owned vault migrations, run before connection reconciliation."""

from pathlib import Path

from migrations._engine import run_migration_plan
from . import _001_operation_grants

_MIGRATIONS = [("001_operation_grants", _001_operation_grants.migrate)]


def run_vault_migrations(vault_dir: Path) -> None:
    """Apply only the vault plan, with its own broker-owned completion ledger."""
    run_migration_plan(vault_dir, _MIGRATIONS)
