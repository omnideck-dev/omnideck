"""The allowlist must stay in step with the tokens the UI actually defines."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from theme.registry import COLOR_SETTINGS, FONT_SETTINGS, SETTING_ALIASES, settings_for
from theme.validation import validate_value

pytestmark = pytest.mark.unit

GLOBAL_CSS = Path(__file__).parents[3] / "server" / "ui" / "src" / "global.css"

# Tokens that are deliberately not themeable: layout, spacing, sizes, depth, motion and shadows.
_NOT_THEMEABLE_PREFIXES = ("shadow-", "radius-", "sp-", "font-size-", "z-", "ease")
_NOT_THEMEABLE_NAMES = {"header-height", "sidebar-width", "flyout-width"}


def _block(css: str, opener: str) -> str:
    start = css.index(opener)
    return css[start : css.index("\n}", start)]


def _tokens(block: str) -> dict[str, str]:
    return {name: value.strip() for name, value in re.findall(r"--([\w-]+)\s*:\s*([^;]+);", block)}


@pytest.fixture(scope="module")
def light_tokens() -> dict[str, str]:
    return _tokens(_block(GLOBAL_CSS.read_text(encoding="utf-8"), ":root {"))


@pytest.fixture(scope="module")
def dark_tokens() -> dict[str, str]:
    return _tokens(_block(GLOBAL_CSS.read_text(encoding="utf-8"), '[data-theme="dark"] {'))


def test_setting_ids_are_unique():
    ids = [setting.id for setting in (*COLOR_SETTINGS, *FONT_SETTINGS)]
    assert len(ids) == len(set(ids))


def test_kinds_match_their_table():
    assert {setting.kind for setting in COLOR_SETTINGS} == {"color"}
    assert {setting.kind for setting in FONT_SETTINGS} == {"font"}
    assert set(settings_for("color")) == {setting.id for setting in COLOR_SETTINGS}
    assert set(settings_for("font")) == {setting.id for setting in FONT_SETTINGS}


@pytest.mark.parametrize("setting", [*COLOR_SETTINGS, *FONT_SETTINGS], ids=lambda s: s.id)
def test_every_default_is_a_value_the_validator_accepts(setting):
    """A user must be able to type back any shipped default, or the grammar is too narrow."""
    assert validate_value(setting, setting.light_default) == setting.light_default
    assert validate_value(setting, setting.dark_default) == setting.dark_default


@pytest.mark.parametrize("setting", COLOR_SETTINGS, ids=lambda s: s.id)
def test_color_defaults_match_global_css(setting, light_tokens, dark_tokens):
    assert setting.light_default == light_tokens[setting.id]
    # A token the dark block does not redefine inherits the light value.
    assert setting.dark_default == dark_tokens.get(setting.id, light_tokens[setting.id])


@pytest.mark.parametrize("setting", FONT_SETTINGS, ids=lambda s: s.id)
def test_font_defaults_match_global_css(setting, light_tokens):
    assert setting.light_default == light_tokens[setting.id]
    assert setting.dark_default == setting.light_default


def test_every_themeable_token_in_global_css_is_in_the_allowlist(light_tokens):
    """A new color or font token must be added to the registry, or be named above as not themeable."""
    themeable = {
        name
        for name in light_tokens
        if name not in _NOT_THEMEABLE_NAMES and not name.startswith(_NOT_THEMEABLE_PREFIXES)
    }
    registered = {setting.id for setting in (*COLOR_SETTINGS, *FONT_SETTINGS)}
    assert themeable == registered


def test_aliases_point_at_real_settings_and_never_shadow_one():
    ids = set(settings_for("color")) | set(settings_for("font"))
    for alias, target in SETTING_ALIASES.items():
        assert target in ids, f"alias {alias!r} points at the unknown setting {target!r}"
        assert alias not in ids, f"alias {alias!r} is also a real setting id"
