"""The generated stylesheet: scoping per mode, allowlist-only output, and a content-based version."""

from __future__ import annotations

import pytest

from theme.css import css_version, render_css
from theme.types import ThemeOverrides

pytestmark = pytest.mark.unit


def test_no_overrides_render_nothing():
    assert render_css(ThemeOverrides()) == ""


def test_light_colors_are_scoped_away_from_dark_mode():
    css = render_css(ThemeOverrides(light={"accent": "#7c3aed"}))
    # Scoped so the rule cannot also win in dark mode, where the app's own dark block applies.
    assert css == ':root:not([data-theme="dark"]) {\n  --accent: #7c3aed;\n}\n'


def test_dark_colors_out_rank_the_apps_dark_block():
    css = render_css(ThemeOverrides(dark={"canvas": "#000000"}))
    assert css == ':root[data-theme="dark"] {\n  --canvas: #000000;\n}\n'


def test_fonts_apply_to_both_modes():
    css = render_css(ThemeOverrides(fonts={"font-body": "'Segoe UI', sans-serif"}))
    assert css == ":root {\n  --font-body: 'Segoe UI', sans-serif;\n}\n"


def test_all_three_groups_render_in_a_stable_order():
    css = render_css(
        ThemeOverrides(
            light={"accent": "#111111", "canvas": "#222222"},
            dark={"accent": "#333333"},
            fonts={"font-code": "monospace"},
        )
    )
    assert css.index(':root:not([data-theme="dark"])') < css.index(':root[data-theme="dark"]') < css.rindex(":root {")
    # Declarations follow the allowlist order (canvas is registered before accent), not insertion order.
    assert css.index("--canvas") < css.index("--accent")


def test_only_allowlisted_settings_are_ever_emitted():
    css = render_css(ThemeOverrides(light={"accent": "#111111", "display": "none", "font-body": "serif"}))
    assert "--accent: #111111;" in css
    assert "display" not in css
    assert "font-body" not in css


def test_version_tracks_the_rendered_content():
    first = render_css(ThemeOverrides(light={"accent": "#111111"}))
    same = render_css(ThemeOverrides(light={"accent": "#111111"}))
    other = render_css(ThemeOverrides(light={"accent": "#222222"}))
    assert css_version(first) == css_version(same)
    assert css_version(first) != css_version(other)
    assert css_version(first) != css_version("")
