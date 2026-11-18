"""Persistence: atomic writes, and a saved file can never smuggle in an unsupported value."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from theme.store import load_overrides, save_overrides
from theme.types import ThemeOverrides

pytestmark = pytest.mark.unit


def test_missing_file_means_no_overrides(theme_file: Path):
    assert not theme_file.exists()
    assert load_overrides().is_empty()


def test_round_trip(theme_file: Path):
    saved = ThemeOverrides(light={"accent": "#7c3aed"}, dark={"canvas": "#000000"}, fonts={"font-code": "monospace"})
    save_overrides(saved)
    assert load_overrides() == saved


def test_save_creates_the_home_directory(theme_file: Path):
    assert not theme_file.parent.exists()
    save_overrides(ThemeOverrides(light={"accent": "#7c3aed"}))
    assert theme_file.exists()


def test_save_leaves_no_temp_files(theme_file: Path):
    save_overrides(ThemeOverrides(light={"accent": "#7c3aed"}))
    save_overrides(ThemeOverrides(light={"accent": "#111111"}))
    assert [p.name for p in theme_file.parent.iterdir()] == ["theme.json"]


def test_failed_replace_keeps_the_previous_file_and_cleans_up(theme_file: Path, monkeypatch: pytest.MonkeyPatch):
    save_overrides(ThemeOverrides(light={"accent": "#7c3aed"}))
    before = theme_file.read_text(encoding="utf-8")

    def boom(self: Path, target: Path) -> None:
        raise OSError("disk full")

    with monkeypatch.context() as patched:
        patched.setattr(Path, "replace", boom)
        with pytest.raises(OSError, match="disk full"):
            save_overrides(ThemeOverrides(light={"accent": "#111111"}))

    assert theme_file.read_text(encoding="utf-8") == before
    assert [p.name for p in theme_file.parent.iterdir()] == ["theme.json"]


@pytest.mark.parametrize("content", ["", "{not json", "[]", '"text"', "null", "42"])
def test_unreadable_or_unexpected_contents_mean_no_overrides(theme_file: Path, content: str):
    theme_file.parent.mkdir(parents=True)
    theme_file.write_text(content, encoding="utf-8")
    assert load_overrides().is_empty()


def test_unsupported_entries_are_dropped_on_load(theme_file: Path):
    """A hand-edited or older file must not be able to put anything outside the allowlist into the UI."""
    theme_file.parent.mkdir(parents=True)
    theme_file.write_text(
        json.dumps(
            {
                "version": 1,
                "light": {
                    "accent": "#7c3aed",
                    "no-such-setting": "#111111",
                    "canvas": "url(https://example.com/x.png)",
                    "surface": 5,
                    "font-body": "serif",
                },
                "dark": {"canvas": "#000000", "elevated": "red; background: blue"},
                "fonts": {"font-code": "monospace", "font-body": "Inter; color: red", "accent": "#111111"},
            }
        ),
        encoding="utf-8",
    )
    assert load_overrides() == ThemeOverrides(
        light={"accent": "#7c3aed"},
        dark={"canvas": "#000000"},
        fonts={"font-code": "monospace"},
    )


@pytest.mark.parametrize("group", ["light", "dark", "fonts"])
def test_a_group_of_the_wrong_shape_is_ignored(theme_file: Path, group: str):
    theme_file.parent.mkdir(parents=True)
    theme_file.write_text(json.dumps({group: ["accent"]}), encoding="utf-8")
    assert load_overrides().is_empty()
