"""Data migrations for on-disk state.

Call ``run_migrations(state_dir)`` from container bootstrap, before either
service starts. Successfully completed
migrations are tracked in ``{state_dir}/.migrations.json``.
"""

from pathlib import Path


def run_migrations(state_dir: Path, vault_dir: Path | None = None) -> None:
    """Load the unified startup plan lazily."""
    from migrations._runner import run_migrations as run_app_migrations

    run_app_migrations(state_dir, vault_dir)

__all__ = ["run_migrations"]
