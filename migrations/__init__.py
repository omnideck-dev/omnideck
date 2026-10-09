"""Data migrations for on-disk state.

Call ``run_migrations(state_dir)`` once at app startup, before the server
begins handling requests. Each migration runs at most once — applied
migrations are tracked in ``{state_dir}/.migrations.json``.
"""

from pathlib import Path


def run_migrations(state_dir: Path) -> None:
    """Load the app plan lazily so vault migrations can reuse only the engine."""
    from migrations._runner import run_migrations as run_app_migrations

    run_app_migrations(state_dir)

__all__ = ["run_migrations"]
