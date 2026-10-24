"""Fixed container bootstrap command: migrate, restore owners, then start services."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import pwd

from migrations import run_migrations


def _restore_owner(
    directory: Path, uid: int, gid: int, *, exclude: Path | None = None, root_only: bool = False
) -> None:
    """Restore store ownership without traversing symlinks or the other store."""
    if not root_only or directory.lstat().st_uid == 0:
        os.chown(directory, uid, gid, follow_symlinks=False)
    for root, dirs, files in os.walk(directory, followlinks=False):
        for name in [*dirs, *files]:
            path = Path(root) / name
            if path == exclude:
                dirs.remove(name)
                continue
            if not root_only or path.lstat().st_uid == 0:
                os.chown(path, uid, gid, follow_symlinks=False)


def bootstrap(
    state_dir: Path, vault_dir: Path, *, app_uid: int, app_gid: int, broker_uid: int, broker_gid: int
) -> None:
    """Run once before privilege drop, repairing write ownership even on failure."""
    state_dir, vault_dir = state_dir.resolve(), vault_dir.resolve()
    if state_dir == vault_dir or vault_dir in state_dir.parents:
        raise ValueError("Application state must not be inside the vault")
    state_dir.mkdir(parents=True, exist_ok=True)
    vault_dir.mkdir(parents=True, exist_ok=True)
    vault_dir.chmod(0o700)
    try:
        run_migrations(state_dir, vault_dir)
    finally:
        # Atomic replacements and new backups created as root must remain usable
        # by the service that owns each store. Do not follow links outside them.
        _restore_owner(state_dir, app_uid, app_gid, exclude=vault_dir)
        _restore_owner(vault_dir, broker_uid, broker_gid)


def main() -> None:
    from config import load_config

    logging.basicConfig(level=logging.INFO)
    if os.geteuid() != 0:
        raise PermissionError("Container migration bootstrap must run before privilege drop")
    app = pwd.getpwnam("omnideck")
    broker = pwd.getpwnam("broker")
    config = load_config()
    state = Path(config.settings.home_dir)
    vault = Path(os.environ.get("SUPERVISOR_VAULT_DIR", "/var/lib/omnideck/vault"))
    try:
        bootstrap(
            state, vault, app_uid=app.pw_uid, app_gid=app.pw_gid, broker_uid=broker.pw_uid, broker_gid=broker.pw_gid
        )
    finally:
        # The historical welcome migration also seeds files in the virtual home.
        # Restore only root-created files, preserving shared downloads ownership.
        home = Path(config.virtual_computer.home_dir)
        if home.is_dir():
            _restore_owner(home, app.pw_uid, app.pw_gid, root_only=True)


if __name__ == "__main__":
    main()
