"""Data migrations for on-disk state.

The container bootstrap supplies explicit application and vault directories
before either service starts. Completed migrations are tracked in the
application state's migration ledger.
"""

from ._runner import run_migrations

__all__ = ["run_migrations"]
