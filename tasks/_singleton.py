"""Process-wide ``TaskStore`` singleton.

Lives in its own module so that both ``tasks.__init__`` (the package facade)
and ``tasks._tools`` (an internal module) can import ``get_store`` without
creating a circular import through the package root.
"""

from __future__ import annotations

from pathlib import Path

from config import load_config
from tasks._file_store import ROUTINES_SUBDIR, FileTaskStore
from tasks._store import TaskStore

_store: TaskStore | None = None


def get_store() -> TaskStore:
    """Return the task store, lazily initializing on first access."""
    global _store
    if _store is None:
        cfg = load_config()
        routines_dir = Path(cfg.routines.routines_dir or Path(cfg.settings.home_dir) / ROUTINES_SUBDIR)
        _store = FileTaskStore(routines_dir, default_timezone=cfg.routines.timezone)
    return _store
