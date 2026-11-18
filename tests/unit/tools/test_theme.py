"""Unit tests for the agent-facing theme tools. Behavior is covered with the theme subsystem itself."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agent_core.tools._callable_schema import callable_to_json_schema
from theme.registry import COLOR_SETTINGS, FONT_SETTINGS
from tools.theme import get_theme, set_theme

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _theme_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "theme.json"
    monkeypatch.setattr("theme.store.theme_path", lambda: path)
    return path


async def test_get_theme_reports_the_supported_settings():
    result = await get_theme()
    assert result["status"] == "ok"
    assert {entry["id"] for entry in result["colors"]} >= {"accent", "canvas", "text-primary"}
    assert {entry["id"] for entry in result["fonts"]} == {"font-brand", "font-body", "font-code"}
    assert result["overrides"] == {"light": {}, "dark": {}, "fonts": {}}


async def test_set_theme_saves_and_get_theme_reflects_it():
    result = await set_theme(
        light={"accent": "#7c3aed"}, dark={"accent": "#a78bfa"}, fonts={"font-body": "Georgia, serif"}
    )
    assert result["status"] == "ok"
    assert result["overrides"] == {
        "light": {"accent": "#7c3aed"},
        "dark": {"accent": "#a78bfa"},
        "fonts": {"font-body": "Georgia, serif"},
    }

    state = await get_theme()
    accent = next(entry for entry in state["colors"] if entry["id"] == "accent")
    assert accent["light"]["effective"] == "#7c3aed"
    assert accent["dark"]["effective"] == "#a78bfa"
    assert state["overrides"] == result["overrides"]


async def test_set_theme_keeps_unspecified_settings_and_supports_reset():
    await set_theme(light={"accent": "#7c3aed"})
    await set_theme(light={"canvas": "#ffffff"})
    assert (await get_theme())["overrides"]["light"] == {"accent": "#7c3aed", "canvas": "#ffffff"}

    cleared = await set_theme(light={"accent": None})
    assert cleared["overrides"]["light"] == {"canvas": "#ffffff"}

    restored = await set_theme(reset=True)
    assert restored["status"] == "ok"
    assert restored["overrides"] == {"light": {}, "dark": {}, "fonts": {}}


async def test_invalid_input_returns_an_error_and_changes_nothing(_theme_file: Path):
    await set_theme(light={"accent": "#7c3aed"})
    before = json.loads(_theme_file.read_text(encoding="utf-8"))

    result = await set_theme(light={"canvas": "red"}, fonts={"font-body": "a; b"})

    assert result["status"] == "error"
    assert "light.canvas" in result["error"]
    assert "fonts.font-body" in result["error"]
    assert json.loads(_theme_file.read_text(encoding="utf-8")) == before


def test_tool_schemas_expose_structured_arguments():
    parameters = callable_to_json_schema(set_theme)["function"]["parameters"]
    assert {name: spec["type"] for name, spec in parameters["properties"].items()} == {
        "light": "object",
        "dark": "object",
        "fonts": "object",
        "reset": "boolean",
    }
    assert all(spec["description"] for spec in parameters["properties"].values())
    # Every argument is optional, so a bare reset or a single-mode change is a valid call.
    assert parameters["required"] == []
    assert callable_to_json_schema(get_theme)["function"]["parameters"]["properties"] == {}


def test_set_theme_description_names_every_supported_setting():
    """A model that skips get_theme can only use the names the description gives it."""
    description = callable_to_json_schema(set_theme)["function"]["description"]
    named = set(re.findall(r"[a-z][a-z-]*[a-z]", description))
    missing = [setting.id for setting in (*COLOR_SETTINGS, *FONT_SETTINGS) if setting.id not in named]
    assert missing == []


async def test_a_guessed_setting_name_gets_a_usable_error():
    result = await set_theme(light={"background": "#ffffff"})
    assert result["status"] == "error"
    assert "did you mean 'canvas'?" in result["error"]
    assert "valid color settings:" in result["error"]


def test_set_theme_description_points_hover_requests_at_both_settings():
    """accent-hover alone only reaches a few buttons and links; most hover highlights use accent-muted."""
    description = callable_to_json_schema(set_theme)["function"]["description"]
    sentences = re.split(r"(?<=[.;])\s+", description)
    assert any("hover" in s.lower() and "accent-muted" in s and "accent-hover" in s for s in sentences)
