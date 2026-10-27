"""Type-based validation of theme values.

Values end up inside a generated stylesheet, so each kind accepts a small fixed
grammar instead of arbitrary text. A color is a hex literal or a numeric
``rgb()``/``rgba()``/``hsl()``/``hsla()`` call; a font is a comma-separated list
of family names. Nothing that can open a new declaration, rule, import, URL or
variable reference fits either grammar.
"""

from __future__ import annotations

import re

from .types import ThemeError, ThemeSetting

COLOR_FORMAT = (
    "a hex color such as #2563eb (3, 4, 6 or 8 digits), rgb()/rgba()/hsl()/hsla() with plain numbers "
    "such as rgba(37,99,235,0.15), or the word transparent"
)
FONT_FORMAT = (
    "a comma-separated list of up to 8 font family names; quote names that contain spaces "
    "(for example 'Segoe UI', Roboto, sans-serif)"
)

_MAX_COLOR_LENGTH = 64
_MAX_FONT_LENGTH = 300
_MAX_FONT_FAMILIES = 8

_HEX_COLOR = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})")
_COLOR_FUNCTION = re.compile(r"(?:rgb|rgba|hsl|hsla)\(([^()]*)\)", re.IGNORECASE)
_COLOR_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:%|deg)?")
_COLOR_SEPARATORS = re.compile(r"[\s,/]+")
_FONT_FAMILY = re.compile(r"""'[\w .-]{1,64}'|"[\w .-]{1,64}"|-?[A-Za-z][\w-]{0,63}""")


def _is_color(value: str) -> bool:
    if len(value) > _MAX_COLOR_LENGTH:
        return False
    if value.lower() == "transparent" or _HEX_COLOR.fullmatch(value):
        return True
    function = _COLOR_FUNCTION.fullmatch(value)
    if function is None:
        return False
    arguments = [part for part in _COLOR_SEPARATORS.split(function.group(1).strip()) if part]
    return len(arguments) in (3, 4) and all(_COLOR_NUMBER.fullmatch(part) for part in arguments)


def _is_font(value: str) -> bool:
    if len(value) > _MAX_FONT_LENGTH:
        return False
    families = [part.strip() for part in value.split(",")]
    if not 1 <= len(families) <= _MAX_FONT_FAMILIES:
        return False
    return all(_FONT_FAMILY.fullmatch(family) for family in families)


def validate_value(setting: ThemeSetting, value: object) -> str:
    """Return ``value`` normalized for storage, or raise ``ThemeError`` if it does not fit the setting's type."""
    if not isinstance(value, str):
        raise ThemeError(f"{setting.id}: expected a string value, got {type(value).__name__}")
    text = value.strip()
    if setting.kind == "color":
        if not _is_color(text):
            raise ThemeError(f"{setting.id}: {value!r} is not a valid color; use {COLOR_FORMAT}")
    elif not _is_font(text):
        raise ThemeError(f"{setting.id}: {value!r} is not a valid font list; use {FONT_FORMAT}")
    return text
