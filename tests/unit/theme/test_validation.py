"""Values are checked by type; anything that could reach beyond a color or font name is rejected."""

from __future__ import annotations

import pytest

from theme.registry import settings_for
from theme.types import ThemeError
from theme.validation import validate_value

pytestmark = pytest.mark.unit

ACCENT = settings_for("color")["accent"]
FONT_BODY = settings_for("font")["font-body"]


@pytest.mark.parametrize(
    "value",
    [
        "#fff",
        "#FFFF",
        "#2563eb",
        "#2563EB80",
        "rgb(1,2,3)",
        "rgba(37, 99, 235, 0.15)",
        "RGBA(37,99,235,.15)",
        "hsl(210 50% 40%)",
        "hsla(210deg, 50%, 40%, 0.5)",
        "hsl(210 50% 40% / 0.5)",
        "transparent",
        "  #2563eb  ",
    ],
)
def test_valid_colors_are_accepted_and_trimmed(value):
    assert validate_value(ACCENT, value) == value.strip()


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "red",
        "purple",
        "#12",
        "#12345",
        "#1234567",
        "#ggg",
        "rgb(1,2)",
        "rgb(1,2,3,4,5)",
        "rgb(a,b,c)",
        "rgb(var(--x),1,2)",
        "rgb(1,2,3) !important",
        "#fff; background: red",
        "#fff} body { display: none",
        "#fff /* comment */",
        "url(https://example.com/x.png)",
        "var(--accent)",
        "expression(alert(1))",
        "#" + "f" * 80,
    ],
)
def test_invalid_colors_are_rejected(value):
    with pytest.raises(ThemeError, match="accent"):
        validate_value(ACCENT, value)


@pytest.mark.parametrize("value", [None, 5, 1.5, True, ["#fff"], {"a": "b"}])
def test_non_string_values_are_rejected(value):
    with pytest.raises(ThemeError, match="expected a string"):
        validate_value(ACCENT, value)


@pytest.mark.parametrize(
    "value",
    [
        "Inter",
        "sans-serif",
        "-apple-system",
        "'Segoe UI', Roboto, sans-serif",
        '"Fira Code", monospace',
        "'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
        "  Georgia , serif ",
        "'Noto Sans JP', sans-serif",
    ],
)
def test_valid_fonts_are_accepted_and_trimmed(value):
    assert validate_value(FONT_BODY, value) == value.strip()


@pytest.mark.parametrize(
    "value",
    [
        "",
        "Inter,",
        ",Inter",
        "Segoe UI",
        "Inter; color: red",
        "Inter } body { display: none",
        "'Inter",
        "Inter'",
        "'Inter\" ",
        "'a'b'",
        "url(https://example.com/font.woff)",
        "@import url(x)",
        "var(--font-code)",
        "'Inter' !important",
        "'x\\' y'",
        "'" + "a" * 70 + "'",
        ", ".join(f"Font{i}" for i in range(9)),
        "a" * 301,
    ],
)
def test_invalid_fonts_are_rejected(value):
    with pytest.raises(ThemeError, match="font-body"):
        validate_value(FONT_BODY, value)


def test_error_message_names_the_setting_and_explains_the_format():
    with pytest.raises(ThemeError) as excinfo:
        validate_value(ACCENT, "red")
    message = str(excinfo.value)
    assert message.startswith("accent:")
    assert "hex color" in message
