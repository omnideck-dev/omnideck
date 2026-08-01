"""Migration 014: Add the automatic software updates preference to settings.json.

The desktop application reads this preference to decide whether to install a
newer release on its own. An install that predates the preference has no key
for it at all, and an absent key must not be read as a choice: this writes the
default so the choice is explicit and the settings page has something to show.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_SETTINGS_FILE = "settings.json"
_KEY = "software_updates_automatic"


def migrate(state_dir: Path) -> None:
    """Seed software_updates_automatic in settings.json if absent."""
    path = state_dir / _SETTINGS_FILE
    if not path.exists():
        # No settings file yet — defaults in settings.py will apply on first read.
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Corrupt %s, skipping migration 014", path)
        return

    if _KEY in data:
        return

    data[_KEY] = False
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.info("Seeded the automatic software updates preference in %s", path)
