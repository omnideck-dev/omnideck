"""The theme contract: discovery, merge-style updates, resets, and all-or-nothing validation."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from theme import ThemeError, get_theme_state, theme_css, theme_version, update_theme
from theme.registry import COLOR_SETTINGS, FONT_SETTINGS

pytestmark = pytest.mark.unit


def _color(state: dict, setting_id: str) -> dict:
    return next(entry for entry in state["colors"] if entry["id"] == setting_id)


def _font(state: dict, setting_id: str) -> dict:
    return next(entry for entry in state["fonts"] if entry["id"] == setting_id)


# --- discovery -------------------------------------------------------------


def test_state_lists_every_supported_setting_with_defaults():
    state = get_theme_state()
    assert [entry["id"] for entry in state["colors"]] == [s.id for s in COLOR_SETTINGS]
    assert [entry["id"] for entry in state["fonts"]] == [s.id for s in FONT_SETTINGS]
    accent = _color(state, "accent")
    assert accent["light"] == {"default": "#2563eb", "override": None, "effective": "#2563eb"}
    assert accent["dark"] == {"default": "#3b82f6", "override": None, "effective": "#3b82f6"}
    assert accent["description"]
    assert state["overrides"] == {"light": {}, "dark": {}, "fonts": {}}
    assert set(state["value_formats"]) == {"color", "font"}


def test_state_distinguishes_default_override_and_effective():
    update_theme(light={"accent": "#7c3aed"}, fonts={"font-code": "monospace"})
    state = get_theme_state()
    assert _color(state, "accent")["light"] == {"default": "#2563eb", "override": "#7c3aed", "effective": "#7c3aed"}
    # Only the light value was changed.
    assert _color(state, "accent")["dark"]["override"] is None
    code = _font(state, "font-code")
    assert code["override"] == "monospace"
    assert code["effective"] == "monospace"
    assert code["default"].startswith("'JetBrains Mono'")
    assert state["overrides"] == {"light": {"accent": "#7c3aed"}, "dark": {}, "fonts": {"font-code": "monospace"}}


# --- updates ---------------------------------------------------------------


def test_update_returns_the_saved_overrides_and_a_version():
    result = update_theme(light={"accent": "#7c3aed"})
    assert result["overrides"] == {"light": {"accent": "#7c3aed"}, "dark": {}, "fonts": {}}
    assert result["version"] == theme_version()


def test_update_preserves_settings_it_does_not_mention():
    update_theme(light={"accent": "#7c3aed"}, dark={"canvas": "#000000"})
    update_theme(light={"surface": "#eeeeee"})
    assert get_theme_state()["overrides"] == {
        "light": {"accent": "#7c3aed", "surface": "#eeeeee"},
        "dark": {"canvas": "#000000"},
        "fonts": {},
    }


def test_update_replaces_the_value_of_a_setting_it_mentions():
    update_theme(light={"accent": "#7c3aed"})
    update_theme(light={"accent": "#111111"})
    assert get_theme_state()["overrides"]["light"] == {"accent": "#111111"}


def test_null_clears_a_single_override():
    update_theme(light={"accent": "#7c3aed", "canvas": "#ffffff"}, fonts={"font-body": "serif"})
    update_theme(light={"accent": None}, fonts={"font-body": None})
    assert get_theme_state()["overrides"] == {"light": {"canvas": "#ffffff"}, "dark": {}, "fonts": {}}


def test_clearing_a_setting_that_was_never_set_is_harmless():
    update_theme(light={"accent": None})
    assert get_theme_state()["overrides"] == {"light": {}, "dark": {}, "fonts": {}}


def test_reset_alone_restores_the_default_theme():
    update_theme(light={"accent": "#7c3aed"}, dark={"canvas": "#000000"}, fonts={"font-body": "serif"})
    result = update_theme(reset=True)
    assert result["overrides"] == {"light": {}, "dark": {}, "fonts": {}}
    assert theme_css() == ""


def test_reset_with_values_replaces_the_whole_theme():
    update_theme(light={"accent": "#7c3aed"}, dark={"canvas": "#000000"})
    update_theme(light={"surface": "#eeeeee"}, reset=True)
    assert get_theme_state()["overrides"] == {"light": {"surface": "#eeeeee"}, "dark": {}, "fonts": {}}


def test_values_are_trimmed_before_saving():
    update_theme(light={"accent": "  #7c3aed  "})
    assert get_theme_state()["overrides"]["light"] == {"accent": "#7c3aed"}


def test_an_update_that_changes_nothing_does_not_write(theme_file: Path):
    update_theme(light={"accent": "#7c3aed"})
    before = theme_file.stat().st_mtime_ns
    update_theme(light={"accent": "#7c3aed"})
    update_theme()
    assert theme_file.stat().st_mtime_ns == before


# --- rejection leaves state untouched --------------------------------------


def test_one_invalid_value_rejects_the_whole_update_and_changes_nothing(theme_file: Path):
    update_theme(light={"accent": "#7c3aed"})
    before = theme_file.read_text(encoding="utf-8")

    with pytest.raises(ThemeError, match="light.canvas"):
        update_theme(light={"surface": "#eeeeee", "canvas": "not-a-color"}, dark={"canvas": "#000000"})

    assert theme_file.read_text(encoding="utf-8") == before
    assert get_theme_state()["overrides"] == {"light": {"accent": "#7c3aed"}, "dark": {}, "fonts": {}}


def test_a_rejected_update_does_not_create_the_file(theme_file: Path):
    with pytest.raises(ThemeError):
        update_theme(light={"accent": "nope"})
    assert not theme_file.exists()


def test_a_rejected_reset_does_not_clear_existing_overrides():
    update_theme(light={"accent": "#7c3aed"})
    with pytest.raises(ThemeError):
        update_theme(light={"accent": "nope"}, reset=True)
    assert get_theme_state()["overrides"]["light"] == {"accent": "#7c3aed"}


def test_every_problem_is_reported_at_once():
    with pytest.raises(ThemeError) as excinfo:
        update_theme(light={"accent": "nope"}, dark={"canvas": 5}, fonts={"font-body": "a; b"})
    message = str(excinfo.value)
    assert "light.accent" in message
    assert "dark.canvas" in message
    assert "fonts.font-body" in message


def test_unknown_setting_suggests_the_closest_match():
    with pytest.raises(ThemeError, match=r"light\.acent: unknown color setting \(did you mean 'accent'\?\)"):
        update_theme(light={"acent": "#7c3aed"})


def test_a_guessed_plain_name_is_pointed_at_the_real_setting():
    with pytest.raises(ThemeError, match=r"light\.background: unknown color setting \(did you mean 'canvas'\?\)"):
        update_theme(light={"background": "#ffffff"})


def test_unknown_color_settings_are_followed_by_the_valid_names_once():
    with pytest.raises(ThemeError) as excinfo:
        update_theme(light={"background": "#ffffff"}, dark={"sidebar": "#000000"})
    message = str(excinfo.value)
    assert message.count("valid color settings:") == 1
    assert "valid color settings: canvas, surface, elevated," in message
    assert "valid font settings" not in message


def test_unknown_font_settings_list_the_valid_fonts():
    pattern = r"fonts\.font: unknown font setting \(did you mean 'font-body'\?\).*valid font settings: font-brand, font-body, font-code"
    with pytest.raises(ThemeError, match=pattern):
        update_theme(fonts={"font": "serif"})


def test_a_wrong_group_error_does_not_dump_the_whole_list():
    with pytest.raises(ThemeError) as excinfo:
        update_theme(light={"font-body": "serif"})
    assert "valid color settings" not in str(excinfo.value)


def test_a_rejected_guess_leaves_the_saved_theme_alone():
    update_theme(light={"accent": "#7c3aed"})
    with pytest.raises(ThemeError):
        update_theme(light={"canvas": "#ffffff", "background": "#000000"})
    assert get_theme_state()["overrides"]["light"] == {"accent": "#7c3aed"}


def test_a_font_id_in_a_color_group_points_to_the_right_group():
    with pytest.raises(ThemeError, match=r"light\.font-body: this is a font setting, set it under 'fonts'"):
        update_theme(light={"font-body": "serif"})


def test_a_color_id_in_the_fonts_group_points_to_the_right_group():
    with pytest.raises(ThemeError, match=r"fonts\.accent: this is a color setting, set it under 'light' or 'dark'"):
        update_theme(fonts={"accent": "#7c3aed"})


@pytest.mark.parametrize("group", ["light", "dark", "fonts"])
@pytest.mark.parametrize("bad", ["#7c3aed", ["accent"], 5])
def test_a_group_must_be_an_object(group: str, bad: object):
    with pytest.raises(ThemeError, match=f"{group}: expected an object"):
        update_theme(**{group: bad})


@pytest.mark.parametrize("unsupported", ["shadow-sm", "radius-md", "z-modal", "header-height", "display", "--accent"])
def test_settings_outside_the_allowlist_cannot_be_written(unsupported: str):
    with pytest.raises(ThemeError, match="unknown"):
        update_theme(light={unsupported: "#000000"})
    with pytest.raises(ThemeError, match="unknown"):
        update_theme(fonts={unsupported: "serif"})


# --- rendering -------------------------------------------------------------


def test_css_and_version_follow_the_saved_theme():
    assert theme_css() == ""
    empty_version = theme_version()

    update_theme(light={"accent": "#7c3aed"})
    assert "--accent: #7c3aed;" in theme_css()
    assert theme_version() != empty_version

    update_theme(reset=True)
    assert theme_css() == ""
    assert theme_version() == empty_version


# --- concurrency -----------------------------------------------------------


def test_concurrent_updates_do_not_lose_each_others_changes():
    ids = [setting.id for setting in COLOR_SETTINGS][:16]
    errors: list[BaseException] = []

    def worker(setting_id: str) -> None:
        try:
            update_theme(light={setting_id: "#123456"})
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(setting_id,)) for setting_id in ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert set(get_theme_state()["overrides"]["light"]) == set(ids)
