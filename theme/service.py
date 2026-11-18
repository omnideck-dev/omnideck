"""The theme subsystem's operations: describe, update, and render the saved theme."""

from __future__ import annotations

import difflib
import threading
from typing import Any

from .css import css_version, render_css
from .registry import COLOR_SETTINGS, FONT_SETTINGS, SETTING_ALIASES, settings_for
from .store import load_overrides, save_overrides
from .types import SettingKind, ThemeError, ThemeOverrides
from .validation import COLOR_FORMAT, FONT_FORMAT, validate_value

# Serializes read-modify-write updates so two concurrent callers cannot lose each other's change.
_update_lock = threading.Lock()

_GROUP_KIND: dict[str, SettingKind] = {"light": "color", "dark": "color", "fonts": "font"}
_KIND_GROUP: dict[SettingKind, str] = {"color": "'light' or 'dark'", "font": "'fonts'"}
# Typed so each element is a SettingKind rather than a bare str when iterated.
_KIND_ORDER: tuple[SettingKind, ...] = ("color", "font")


def _view(default: str, override: str | None) -> dict[str, str | None]:
    return {"default": default, "override": override, "effective": default if override is None else override}


def theme_css() -> str:
    """The stylesheet for the saved theme; empty when nothing is overridden."""
    return render_css(load_overrides())


def theme_version() -> str:
    """Identifier that changes exactly when the rendered theme changes."""
    return css_version(theme_css())


def _summary(overrides: ThemeOverrides) -> dict[str, Any]:
    return {
        "version": css_version(render_css(overrides)),
        "overrides": {"light": dict(overrides.light), "dark": dict(overrides.dark), "fonts": dict(overrides.fonts)},
    }


def get_theme_state() -> dict[str, Any]:
    """Describe every supported setting with its default, saved override and effective value."""
    overrides = load_overrides()
    colors = [
        {
            "id": setting.id,
            "description": setting.description,
            "light": _view(setting.light_default, overrides.light.get(setting.id)),
            "dark": _view(setting.dark_default, overrides.dark.get(setting.id)),
        }
        for setting in COLOR_SETTINGS
    ]
    fonts = [
        {
            "id": setting.id,
            "description": setting.description,
            **_view(setting.light_default, overrides.fonts.get(setting.id)),
        }
        for setting in FONT_SETTINGS
    ]
    return {
        **_summary(overrides),
        "value_formats": {"color": COLOR_FORMAT, "font": FONT_FORMAT},
        "colors": colors,
        "fonts": fonts,
    }


def _unknown_setting_message(group: str, key: object, kind: SettingKind) -> tuple[str, bool]:
    """Describe a rejected setting id; the flag says whether the valid ids should be listed too."""
    known = settings_for(kind)
    text = str(key)
    other_kind: SettingKind = "font" if kind == "color" else "color"
    if text in settings_for(other_kind):
        return f"{group}.{text}: this is a {other_kind} setting, set it under {_KIND_GROUP[other_kind]}", False
    alias = SETTING_ALIASES.get(text.strip().lower().replace("_", "-").replace(" ", "-"))
    close = [alias] if alias in known else difflib.get_close_matches(text, known, n=1)
    hint = f" (did you mean '{close[0]}'?)" if close else ""
    return f"{group}.{text}: unknown {kind} setting{hint}", True


def _valid_settings_message(kinds: set[SettingKind]) -> str:
    """Name every valid id of the given kinds, so a caller's retry does not have to guess again."""
    listed = [f"valid {kind} settings: {', '.join(settings_for(kind))}" for kind in _KIND_ORDER if kind in kinds]
    return "; ".join(listed) + " (get_theme describes each one)"


def _apply_group(
    target: dict[str, str],
    updates: object,
    group: str,
    errors: list[str],
    unknown_kinds: set[SettingKind],
) -> None:
    """Merge ``updates`` into ``target``; a ``None`` value clears that setting.

    Problems are appended to ``errors``, and the kinds that had an unrecognized id to ``unknown_kinds``.
    """
    if updates is None:
        return
    if not isinstance(updates, dict):
        errors.append(f"{group}: expected an object mapping setting ids to values")
        return
    kind = _GROUP_KIND[group]
    known = settings_for(kind)
    for key, value in updates.items():
        setting = known.get(key) if isinstance(key, str) else None
        if setting is None:
            message, list_valid = _unknown_setting_message(group, key, kind)
            errors.append(message)
            if list_valid:
                unknown_kinds.add(kind)
        elif value is None:
            target.pop(key, None)
        else:
            try:
                target[key] = validate_value(setting, value)
            except ThemeError as exc:
                errors.append(f"{group}.{exc}")


def update_theme(
    *,
    light: object = None,
    dark: object = None,
    fonts: object = None,
    reset: bool = False,
) -> dict[str, Any]:
    """Apply the given changes to the saved theme and return the resulting overrides.

    Settings that are not mentioned keep their saved value. ``reset`` clears every
    saved override first, so combined with values it replaces the whole theme. The
    update is all-or-nothing: if anything in it is invalid, nothing is saved and
    the error lists every problem found.

    Raises:
        ThemeError: If any part of the update is invalid.
    """
    with _update_lock:
        current = load_overrides()
        updated = ThemeOverrides() if reset else current.copy()
        errors: list[str] = []
        unknown_kinds: set[SettingKind] = set()
        _apply_group(updated.light, light, "light", errors, unknown_kinds)
        _apply_group(updated.dark, dark, "dark", errors, unknown_kinds)
        _apply_group(updated.fonts, fonts, "fonts", errors, unknown_kinds)
        if unknown_kinds:
            errors.append(_valid_settings_message(unknown_kinds))
        if errors:
            raise ThemeError("; ".join(errors))
        if updated != current:
            save_overrides(updated)
        return _summary(updated)
