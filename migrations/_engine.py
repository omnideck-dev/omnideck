"""Ordered migration execution and the single application-state ledger."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

logger = logging.getLogger(__name__)
_APPLIED_FILE = ".migrations.json"


def _load_applied(state_dir: Path) -> set[str]:
    path = state_dir / _APPLIED_FILE
    if not path.exists():
        return set()
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or any(not isinstance(name, str) or not name for name in value):
        raise ValueError(f"Invalid migration history: {path}")
    return set(value)


def _save_applied(state_dir: Path, applied: set[str]) -> None:
    path = state_dir / _APPLIED_FILE
    # mkstemp creates an owner-only file before any data is written. Atomic
    # replacement avoids truncating the ledger if startup is interrupted.
    fd, temporary = tempfile.mkstemp(prefix=".migrations-", dir=state_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(sorted(applied), indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def run_migration_plan(
    state_dir: Path,
    migrations: Sequence[tuple[str, Callable[[Path], None]]],
) -> None:
    """Run all pending migrations against the state directory."""
    state_dir = Path(state_dir)
    if not state_dir.is_dir():
        logger.debug("State directory %s does not exist, skipping migrations", state_dir)
        return

    applied = _load_applied(state_dir)
    pending = [(name, fn) for name, fn in migrations if name not in applied]

    if not pending:
        return

    logger.info("%d pending migration(s)", len(pending))
    for name, fn in pending:
        logger.info("Running migration: %s", name)
        fn(state_dir)
        applied.add(name)
        _save_applied(state_dir, applied)
        logger.info("Migration complete: %s", name)
