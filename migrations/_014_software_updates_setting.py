"""Migration 014: Add the software update preferences to settings.json.

The desktop application reads these to decide whether to install a newer
release on its own and whether to say anything when one appears. An install
that predates them has no keys at all, and an absent key is not a choice: this
writes the defaults so the settings page has something to show and the desktop
application has something to read.

Running Omnideck from the command line ignores both keys, so seeding them there
changes nothing.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_SETTINGS_FILE = "settings.json"
_DEFAULTS = {
    "software_updates_automatic": True,
    "software_updates_notify": True,
}


def migrate(state_dir: Path) -> None:
    """Seed the software update preferences in settings.json if absent."""
    path = state_dir / _SETTINGS_FILE
    if not path.exists():
        # No settings file yet — defaults in settings.py will apply on first read.
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Corrupt %s, skipping migration 014", path)
        return

    missing = {key: value for key, value in _DEFAULTS.items() if key not in data}
    if not missing:
        return

    data.update(missing)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.info("Seeded the software update preferences in %s", path)
