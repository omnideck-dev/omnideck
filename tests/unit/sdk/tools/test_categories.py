"""Unit tests for the standard tool-category registry.

A category groups related tools under a stable id and is the unit a skill
grants. These tests cover the standard (non-integration) categories: which
categories the feature flags expose, that they carry UI metadata, that their
loaders resolve to real callables, and that local-grounding tools drop out
when visual grounding is disabled.
"""

import pytest

from config import FeaturesConfig
from sdk.tools._categories import category_tools, get_category, list_categories

_EXPECTED_STD_IDS = {
    "coding",
    "browser",
    "webfetch",
    "memory",
    "planning",
    "image_generation",
    "music_generation",
    "desktop",
    "custom_tools",
}


def _features(**overrides) -> FeaturesConfig:
    """A FeaturesConfig with every gate on unless overridden."""
    base = {
        "image_generation": True,
        "music_generation": True,
        "desktop": True,
        "visual_grounding": True,
        "custom_tools": True,
    }
    base.update(overrides)
    return FeaturesConfig(**base)


@pytest.mark.unit
def test_lists_all_standard_categories_when_features_enabled() -> None:
    ids = {c.id for c in list_categories(_features())}
    assert ids == _EXPECTED_STD_IDS


@pytest.mark.unit
@pytest.mark.parametrize(
    "flag",
    ["desktop", "image_generation", "music_generation", "custom_tools"],
)
def test_feature_gated_category_hidden_when_flag_off(flag: str) -> None:
    ids = {c.id for c in list_categories(_features(**{flag: False}))}
    assert flag not in ids
    # An ungated category is unaffected.
    assert "coding" in ids


@pytest.mark.unit
def test_every_listed_category_has_ui_metadata() -> None:
    for c in list_categories(_features()):
        assert c.label, f"{c.id} missing label"
        assert c.description, f"{c.id} missing description"
        assert c.icon.startswith("bi-"), f"{c.id} icon is not a Bootstrap Icon"
        assert c.kind == "std"


@pytest.mark.unit
def test_category_tools_resolve_to_callables() -> None:
    tools = category_tools("coding", _features())
    assert tools
    assert all(callable(t) for t in tools)
    names = {t.__name__ for t in tools}
    assert {"read_file", "run_bash_cmd"} <= names


@pytest.mark.unit
def test_browser_grounding_tool_stripped_when_visual_grounding_off() -> None:
    on = {t.__name__ for t in category_tools("browser", _features(visual_grounding=True))}
    off = {t.__name__ for t in category_tools("browser", _features(visual_grounding=False))}
    assert "browser_visual_action" in on
    assert "browser_visual_action" not in off
    # Non-grounding browser tools survive the strip.
    assert "goto" in off


@pytest.mark.unit
def test_desktop_grounding_tool_stripped_when_visual_grounding_off() -> None:
    on = {t.__name__ for t in category_tools("desktop", _features(visual_grounding=True))}
    off = {t.__name__ for t in category_tools("desktop", _features(visual_grounding=False))}
    assert "perform_visual_action" in on
    assert "perform_visual_action" not in off
    assert "mouse_click" in off


@pytest.mark.unit
def test_unknown_category_resolves_to_empty() -> None:
    assert category_tools("does-not-exist", _features()) == []


@pytest.mark.unit
def test_feature_gated_category_tools_empty_when_flag_off() -> None:
    assert category_tools("desktop", _features(desktop=False)) == []


@pytest.mark.unit
def test_custom_tools_category_resolves_when_feature_on() -> None:
    names = {t.__name__ for t in category_tools("custom_tools", _features(custom_tools=True))}
    assert {"create_custom_tool", "run_custom_tool", "lookup_custom_tools"} <= names


@pytest.mark.unit
def test_custom_tools_category_empty_when_feature_off() -> None:
    assert category_tools("custom_tools", _features(custom_tools=False)) == []


@pytest.mark.unit
def test_get_category_returns_definition_or_none() -> None:
    assert get_category("memory").id == "memory"
    assert get_category("nope") is None
