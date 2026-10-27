"""Persistence of saved theme overrides in ``theme.json`` beside the app settings."""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

from config import load_config

from .registry import settings_for
from .types import SettingKind, ThemeError, ThemeOverrides
from .validation import validate_value

logger = logging.getLogger(__name__)

THEME_FILENAME = "theme.json"
_FORMAT_VERSION = 1


def theme_path() -> Path:
    """Location of the saved theme, in the app home next to the settings file."""
    return Path(load_config().settings.home_dir) / THEME_FILENAME


def _clean(group: str, raw: object, kind: SettingKind) -> dict[str, str]:
    """Keep the entries of one group that are still on the allowlist and still valid.

    The file is re-checked on every read, so a hand-edited file, or one written by
    an older version with a different allowlist, can never put an unsupported
    value into the generated stylesheet.
    """
    if not isinstance(raw, dict):
        logger.warning("Ignoring theme group %r: expected an object", group)
        return {}
    known = settings_for(kind)
    cleaned: dict[str, str] = {}
    for key, value in raw.items():
        setting = known.get(key)
        if setting is None:
            logger.warning("Ignoring unknown theme setting %s.%s", group, key)
            continue
        try:
            cleaned[key] = validate_value(setting, value)
        except ThemeError as exc:
            logger.warning("Ignoring invalid saved theme value %s.%s", group, exc)
    return cleaned


def load_overrides() -> ThemeOverrides:
    """Read the saved overrides; a missing or unreadable file means no overrides."""
    path = theme_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ThemeOverrides()
    except (OSError, json.JSONDecodeError):
        logger.warning("Unreadable theme file %s, using the default theme", path)
        return ThemeOverrides()
    if not isinstance(data, dict):
        logger.warning("Unexpected contents in theme file %s, using the default theme", path)
        return ThemeOverrides()
    return ThemeOverrides(
        light=_clean("light", data.get("light", {}), "color"),
        dark=_clean("dark", data.get("dark", {}), "color"),
        fonts=_clean("fonts", data.get("fonts", {}), "font"),
    )


def save_overrides(overrides: ThemeOverrides) -> None:
    """Write the overrides atomically, so a reader never sees a half-written file."""
    path = theme_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": _FORMAT_VERSION,
        "light": overrides.light,
        "dark": overrides.dark,
        "fonts": overrides.fonts,
    }
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, suffix=".tmp", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        tmp = Path(f.name)
    try:
        tmp.replace(path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
