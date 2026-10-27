"""Plain data types for the theme subsystem. Imports nothing from the project."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SettingKind = Literal["color", "font"]


class ThemeError(ValueError):
    """An invalid theme update. The message is written for the agent to act on."""


@dataclass(frozen=True)
class ThemeSetting:
    """One overridable appearance variable, backed by an existing CSS token."""

    id: str
    kind: SettingKind
    description: str
    light_default: str
    dark_default: str

    @property
    def css_var(self) -> str:
        """The CSS custom property this setting overrides."""
        return f"--{self.id}"


@dataclass
class ThemeOverrides:
    """Saved overrides: colors are kept per mode, fonts are shared by both modes."""

    light: dict[str, str] = field(default_factory=dict)
    dark: dict[str, str] = field(default_factory=dict)
    fonts: dict[str, str] = field(default_factory=dict)

    def copy(self) -> ThemeOverrides:
        """Return an independent copy, so an update can be built without touching the saved one."""
        return ThemeOverrides(light=dict(self.light), dark=dict(self.dark), fonts=dict(self.fonts))

    def is_empty(self) -> bool:
        """True when no setting is overridden."""
        return not (self.light or self.dark or self.fonts)
