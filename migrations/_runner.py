"""Migration runner — applies pending migrations in a fixed order."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from pathlib import Path
import fcntl

from brokering.migrations._001_operation_grants import migrate as _broker_operation_grants

from migrations._001_task_agent_to_profile import migrate as _001_task_agent_to_profile
from migrations._002_install_default_profiles import migrate as _002_install_default_profiles
from migrations._003_vision_settings import migrate as _003_vision_settings
from migrations._004_rename_num_ctx import migrate as _004_rename_num_ctx
from migrations._005_multi_provider import migrate as _005_multi_provider
from migrations._006_install_default_skills import migrate as _006_install_default_skills
from migrations._007_events_first import migrate as _007_events_first
from migrations._008_scrub_browser_screenshots import migrate as _008_scrub_browser_screenshots
from migrations._009_terminal_sidecar import migrate as _009_terminal_sidecar
from migrations._010_backfill_artifacts_index import migrate as _010_backfill_artifacts_index
from migrations._011_seed_welcome_conversation import migrate as _011_seed_welcome_conversation
from migrations._012_computron_path_rename import migrate as _012_computron_path_rename
from migrations._013_goals_to_routines import migrate as _013_goals_to_routines
from migrations._014_software_updates_setting import migrate as _014_software_updates_setting
from migrations._015_browser_profiles import migrate as _015_browser_profiles
from migrations._016_connection_tool_categories import migrate_connections, cleanup, NAME, CLEANUP_NAME

from migrations._engine import _load_applied, _save_applied, run_migration_plan


# Migrations run top-to-bottom on first startup; already-applied entries are
# skipped on subsequent runs. Insert new migrations at the bottom — the order
# must stay stable across releases.
def _migration_plan(vault_dir: Path) -> list[tuple[str, Callable[[Path], None]]]:
    """The one ordered registry, including migrations spanning both stores."""
    return [
        ("001_task_agent_to_profile", _001_task_agent_to_profile),
        ("002_install_default_profiles", _002_install_default_profiles),
        ("003_vision_settings", _003_vision_settings),
        ("004_rename_num_ctx", _004_rename_num_ctx),
        ("005_multi_provider", _005_multi_provider),
        ("006_install_default_skills", _006_install_default_skills),
        ("007_events_first", _007_events_first),
        ("008_scrub_browser_screenshots", _008_scrub_browser_screenshots),
        ("009_terminal_sidecar", _009_terminal_sidecar),
        ("010_backfill_artifacts_index", _010_backfill_artifacts_index),
        ("011_seed_welcome_conversation", _011_seed_welcome_conversation),
        ("012_computron_path_rename", _012_computron_path_rename),
        ("013_goals_to_routines", _013_goals_to_routines),
        ("014_software_updates_setting", _014_software_updates_setting),
        ("015_browser_profiles", _015_browser_profiles),
        ("broker:001_operation_grants", lambda _state: _broker_operation_grants(vault_dir)),
        (NAME, partial(migrate_connections, vault_dir=vault_dir)),
        (CLEANUP_NAME, cleanup),
    ]


def run_migrations(state_dir: Path, vault_dir: Path | None = None) -> None:
    """Import legacy histories without replay, then run before either service.

    Existing app IDs are unchanged. The old vault ledger is read-only historical
    input; broker IDs are namespaced in the existing app ledger. Invalid history
    aborts before any migration runs. The lock covers import and execution.
    """
    state_dir = Path(state_dir)
    if not state_dir.is_dir():
        return
    vault_dir = Path(vault_dir) if vault_dir is not None else state_dir / "vault"
    if vault_dir.resolve() == state_dir.resolve():
        raise ValueError("Vault and application state must be separate directories")
    with (state_dir / ".migrations.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        applied = _load_applied(state_dir)
        imported = {f"broker:{name}" for name in _load_applied(vault_dir)}
        if imported - applied:
            _save_applied(state_dir, applied | imported)
        run_migration_plan(state_dir, _migration_plan(vault_dir))
