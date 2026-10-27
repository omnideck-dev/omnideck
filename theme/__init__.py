"""Shared theme subsystem: the supported appearance settings and their persistence."""

from .service import get_theme_state, theme_css, theme_version, update_theme
from .types import ThemeError

__all__ = ["ThemeError", "get_theme_state", "theme_css", "theme_version", "update_theme"]
